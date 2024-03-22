import os
import subprocess
import logging
import tempfile
import time

logging.basicConfig(level=logging.INFO)

# Define a list of developers, where each developer is a tuple containing their identifiers
developers = [
]

# Define the time difference for consecutive commits from one author to be squashed
SQUASH_TIME_DIFFERENCE = 60 * 60 * 24 * 14  # 2 weeks in seconds

# Define the age limit for squashing commits
SQUASH_AGE_LIMIT = 60 * 60 * 24 * 14

# Flatten the developer identifiers into a dictionary for easy lookup
# Convert all identifiers to lowercase for case-insensitive comparison
author_map = {identifier.lower(): dev[0] for dev in developers for identifier in dev if identifier}


def run_git_command(command, timeout=30, check=True):
    """Run a git command with a timeout and return its output, optionally check for errors."""
    try:
        process = subprocess.run(['git'] + command, capture_output=True, text=True, timeout=timeout)
        if check and process.returncode != 0:
            raise Exception(f"Git command failed: {' '.join(command)}\n{process.stderr}")
        return process.stdout.strip()
    except subprocess.TimeoutExpired:
        raise Exception(f"Git command timed out: {' '.join(command)}")


def get_branches():
    """Get a list of all branches."""
    branches = run_git_command(['branch', '-r'])
    if branches:
        branches = branches.split('\n')
        return [branch.strip().replace('origin/', '') for branch in branches if '->' not in branch]
    else:
        logging.error("Failed to get branches.")
        exit()


def get_canonical_author(author):
    """Get the canonical author identity, ignoring capitalization."""
    return author_map.get(author.lower(), author)


def squash_commits(branch):
    """Squash commits by mapped authors using git rebase in an automated way."""
    try:
        # Check out the branch
        run_git_command(['checkout', branch])
    except Exception as e:
        logging.error(f"Checkout failed: {e}")
        return  # Exit the function if checkout fails

    # Get the list of commits in reverse order (oldest first)
    commits = run_git_command(['log', '--reverse', '--pretty=format:%H %an <%ae> %ct', branch]).split('\n')

    squashed_commits = []
    current_squash_group = []

    for i, commit_info in enumerate(commits):
        commit_data = commit_info.rsplit(' ', 3)
        current_commit, current_author, current_timestamp, parents = commit_data
        parent_count = len(parents.split())

        # Get the canonical author identity
        current_author = get_canonical_author(current_author)

        # Get the commit message for further checks
        commit_message = run_git_command(['log', '--format=%B', '-n', '1', current_commit])

        # Determine if this is a revert commit or a tagged commit
        is_revert_commit = 'revert' in commit_message.lower()
        is_tagged_commit = run_git_command(['tag', '--contains', current_commit]) != ''

        # Check if the current commit is older than the SQUASH_AGE_LIMIT
        if time.time() - int(current_timestamp) > SQUASH_AGE_LIMIT:
            continue

        # If it's a special commit, process the current squash group and skip adding the special commit to any group
        if is_revert_commit or is_tagged_commit:
            if len(current_squash_group) > 1:
                # Squash the current group of commits
                start = current_squash_group[0][0]
                end = current_squash_group[-1][0]
                squash_commit_group(current_squash_group, start, end)
                squashed_commits.append((current_squash_group, end))
            current_squash_group = []  # Reset the squash group
            continue  # Skip the special commit and continue with the next commit

        # Determine if the next commit should be added to the current squash group
        if i < len(commits) - 1:
            next_commit_info = commits[i + 1].rsplit(' ', 3)
            next_commit, next_author, next_timestamp = next_commit_info[:3]
            next_author = get_canonical_author(next_author)
            time_difference = int(next_timestamp) - int(current_timestamp)

            if current_author == next_author and 0 < time_difference <= SQUASH_TIME_DIFFERENCE:
                current_squash_group.append((current_commit, current_author))
            else:
                # Process the current squash group if the next author is different or the time difference is too large
                if len(current_squash_group) > 1:
                    start = current_squash_group[0][0]
                    end = current_commit
                    squash_commit_group(current_squash_group, start, end)
                    squashed_commits.append((current_squash_group, end))
                current_squash_group = [(current_commit, current_author)]
        else:
            # If it's the last commit in the list, add it to the current squash group
            current_squash_group.append((current_commit, current_author))

    # Log the squashed commits
    for old_commits, new_commit in squashed_commits:
        squashed_commit_message = run_git_command(['log', '--format=%B', '-n', '1', new_commit])
        logging.info(
            f"Commits {[(commit, author) for commit, author in old_commits]} were squashed into:\n{new_commit}: {squashed_commit_message.strip()}")


def squash_commit_group(commit_group, start, end):
    """Squash a group of commits."""
    combined_message = '\n\n'.join(
        [run_git_command(['log', '--format=%B', '-n', '1', commit]) for commit, _ in commit_group])

    tmpfile_name = None
    try:
        # Create a temporary file to write the new commit message to
        with tempfile.NamedTemporaryFile(mode='w+', delete=False) as tmpfile:
            tmpfile.write(combined_message)
            tmpfile_name = tmpfile.name

        # Perform the rebase without the interactive mode
        run_git_command(['rebase', '--onto', start + '^', start, end, '--msg-file', tmpfile_name])
    except Exception as e:
        logging.error(f"Rebase failed: {e}")
    finally:
        # Remove the temporary file if it was created
        if tmpfile_name and os.path.exists(tmpfile_name):
            os.remove(tmpfile_name)


def main():
    branches = get_branches()

    for branch in branches:
        squash_commits(branch)

    print("Done squashing commits. Please review the changes before pushing.")
    print("If you're satisfied with the changes, you can push all branches to the new repository with:")
    print("git push --all <new-repo-url>")


if __name__ == "__main__":
    main()
