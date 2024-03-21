import subprocess
import logging
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


def run_git_command(command):
    """Run a git command and return its output."""
    process = subprocess.run(['git'] + command, capture_output=True, text=True)
    if process.returncode != 0:
        raise Exception(f"Git command failed: {' '.join(command)}\n{process.stderr}")
    return process.stdout.strip()


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
    """Squash commits by mapped authors."""
    # Check out the branch
    run_git_command(['checkout', branch])

    # Get the list of commits in reverse order (oldest first)
    commits = run_git_command(['log', '--reverse', '--pretty=format:%H %an <%ae> %ct', branch]).split('\n')

    squashed_commits = []
    current_squash_group = []

    for i in range(len(commits) - 1):
        current_commit, current_author, current_timestamp = commits[i].rsplit(' ', 2)
        next_commit, next_author, next_timestamp = commits[i + 1].rsplit(' ', 2)

        # Get the canonical author identities
        current_author = get_canonical_author(current_author)
        next_author = get_canonical_author(next_author)

        # Calculate the time difference between the current commit and the next commit
        time_difference = abs(int(current_timestamp) - int(next_timestamp))

        if current_author == next_author and time_difference <= SQUASH_TIME_DIFFERENCE:  # 2 weeks in seconds
            # Add the current commit to the squash group
            current_squash_group.append(current_commit.split(' ')[0])  # Only add the commit hash
        else:
            # Squash the current group of commits if there's more than one commit in the group
            if current_squash_group and len(current_squash_group) > 1:
                run_git_command(['reset', '--soft', current_squash_group[0] + '^'])
                run_git_command(['commit', '-m', 'Squashed commit'])
                squashed_commits.append(
                    (current_squash_group, current_commit.split(' ')[0]))  # Only add the commit hash
            current_squash_group = []

        # If the last commit was part of a squash, handle it separately
        last_commit, last_author, last_timestamp = commits[-1].rsplit(' ', 2)
        last_author = get_canonical_author(last_author)
        if commits[-2].rsplit(' ', 2)[1].lower() == last_author.lower() and int(
                last_timestamp) <= time.time() - SQUASH_AGE_LIMIT:  # 2 months in seconds
            current_squash_group.append(commits[-2].rsplit(' ', 2)[0].split(' ')[0])  # Only add the commit hash
            if len(current_squash_group) > 1:
                # Get the hash of the root commit
                root_commit = run_git_command(['rev-list', '--max-parents=0', 'HEAD'])
                run_git_command(['reset', '--soft', root_commit])
                run_git_command(['commit', '-m', 'Squashed commit'])
                squashed_commits.append((current_squash_group, last_commit.split(' ')[0]))  # Only

    # Log the squashed commits and concatenate the commit messages
    for old_commits, new_commit in squashed_commits:
        run_git_command(['log', '--format=%B', '-n', '1', new_commit])
        concatenated_message = ""
        for old_commit in old_commits:
            old_message = run_git_command(
                ['log', '--format=%B', '-n', '1', old_commit.split(' ')[0]])  # Only use the commit hash
            concatenated_message += repr(old_message.strip()) + "\n"
        run_git_command(['commit', '--amend', '-m', concatenated_message])
        logging.info(f"was squashed into:\n{new_commit}: {concatenated_message.strip()}")


def main():
    branches = get_branches()

    for branch in branches:
        squash_commits(branch)

    print("Done squashing commits. Please review the changes before pushing.")
    print("If you're satisfied with the changes, you can push all branches to the new repository with:")
    print("git push --all <new-repo-url>")


if __name__ == "__main__":
    main()
