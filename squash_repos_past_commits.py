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
SQUASH_AGE_LIMIT = 60 * 60 * 24 * 60  # 2 months in seconds

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

    for i in range(len(commits)):
        current_commit, current_author, current_timestamp = commits[i].rsplit(' ', 2)

        # Determine if this is the last commit
        is_last_commit = (i == len(commits) - 1)

        # Get the canonical author identities
        current_author = get_canonical_author(current_author)

        # Calculate the time difference between the current commit and the next commit
        if not is_last_commit:
            next_commit, next_author, next_timestamp = commits[i + 1].rsplit(' ', 2)
            next_author = get_canonical_author(next_author)
            time_difference = int(next_timestamp) - int(current_timestamp)
        else:
            time_difference = None

        # Check if the current commit is older than the SQUASH_AGE_LIMIT
        if time.time() - int(current_timestamp) > SQUASH_AGE_LIMIT:
            continue

        # Determine if commits should be squashed
        if not is_last_commit and current_author == next_author and time_difference > 0 and time_difference <= SQUASH_TIME_DIFFERENCE:
            # Add the current commit and author to the squash group
            current_squash_group.append((current_commit, current_author))
        else:
            # Squash the current group of commits if there's more than one commit in the group
            if len(current_squash_group) > 1:
                start = current_squash_group[0][0]
                end = current_commit  # Use the current commit as the end if it's the last or the authors differ

                # Combine commit messages from the squashed commits
                combined_message = '\n\n'.join(
                    [run_git_command(['log', '--format=%B', '-n', '1', commit]) for commit, _ in
                     current_squash_group])

                tmpfile_name = None
                try:
                    # Create a temporary file to write the new commit message to
                    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as tmpfile:
                        tmpfile.write(combined_message)
                        tmpfile_name = tmpfile.name

                    # Perform the rebase without the interactive mode
                    run_git_command(['rebase', '--onto', start + '^', start, end, '--msg-file', tmpfile_name])

                    squashed_commits.append((current_squash_group, end))
                except Exception as e:
                    logging.error(f"Rebase failed: {e}")
                    break
                finally:
                    # Remove the temporary file if it was created
                    if tmpfile_name and os.path.exists(tmpfile_name):
                        os.remove(tmpfile_name)

            # Reset the current squash group for the next round of squashing
            current_squash_group = [(current_commit, current_author)] if not is_last_commit else []

    # Log the squashed commits
    for old_commits, new_commit in squashed_commits:
        squashed_commit_message = run_git_command(['log', '--format=%B', '-n', '1', new_commit])
        logging.info(
            f"Commits {[(commit, author) for commit, author in old_commits]} were squashed into:\n{new_commit}: {squashed_commit_message.strip()}")


def main():
    branches = get_branches()

    for branch in branches:
        squash_commits(branch)

    print("Done squashing commits. Please review the changes before pushing.")
    print("If you're satisfied with the changes, you can push all branches to the new repository with:")
    print("git push --all <new-repo-url>")


if __name__ == "__main__":
    main()
