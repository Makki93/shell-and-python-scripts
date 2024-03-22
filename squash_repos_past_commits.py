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

# Create a dictionary mapping each identifier to the primary email of a developer
author_map = {identifier.lower(): dev[0].lower() for dev in developers for identifier in dev}


def run_git_command(command, timeout=30):
    """Run a git command with a timeout and return its output, check for errors."""
    try:
        process = subprocess.run(['git'] + command, capture_output=True, text=True, timeout=timeout)
        process.check_returncode()  # This will raise CalledProcessError if the command failed
        return process.stdout.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Git command failed with error: {e.stderr}")
        raise  # Re-raise the exception to be caught by the calling function
    except subprocess.TimeoutExpired as e:
        logging.error(f"Git command timed out: {' '.join(command)}")
        raise  # Re-raise the exception to be caught by the calling function


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
    """Get the canonical author identity by checking against all known identifiers."""
    # Look up the primary email using the provided author identifier
    return author_map.get(author.lower(), author)


def extract_jira_number(commit_message):
    """
   Extracts a JIRA issue key (with a project key and a maximum five-digit number) from the commit message.
   Returns the JIRA key if found, otherwise None.
   """
    match = re.search(r'\b[A-Z]+-\d{1,5}\b', commit_message)
    return match.group() if match else None


def squash_commits(branch):
    """Squash commits by mapped authors using git rebase in an automated way."""
    try:
        # Check out the branch
        run_git_command(['checkout', branch])
    except Exception as e:
        logging.error(f"An error occurred while processing {branch}: {e}")
        logging.info("Attempting to reset the branch to its original state.")
        try:
            run_git_command(['reset', '--hard', 'ORIG_HEAD'])  # Reset to the state before rebase
            logging.info(f"Branch {branch} has been reset to its original state.")
        except Exception as reset_e:
            logging.error(f"Failed to reset branch {branch}: {reset_e}")
        raise  # Re-raise the original exception to stop the script

    # Get the list of commits in reverse order (oldest first)
    commits = run_git_command(['log', '--reverse', '--pretty=format:%H %an <%ae> %ct', branch]).split('\n')

    squashed_commits = []
    current_squash_group = []
    current_jira_number = None  # Keep track of the current JIRA number

    for i, commit_info in enumerate(commits):
        commit_data = commit_info.rsplit(' ', 3)
        current_commit, current_author, current_timestamp = commit_data[:3]

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
            current_jira_number = None  # Reset the JIRA number
            continue  # Skip the special commit and continue with the next commit

        # Extract JIRA number from the current commit message
        commit_jira_number = extract_jira_number(commit_message)

        # Determine if the next commit should be added to the current squash group
        if i < len(commits) - 1:
            next_commit_info = commits[i + 1].rsplit(' ', 3)
            next_commit, next_author, next_timestamp = next_commit_info[:3]
            next_author = get_canonical_author(next_author)
            time_difference = int(next_timestamp) - int(current_timestamp)

            # Check if current and next commits are from the same author
            if current_author == next_author and 0 < time_difference <= SQUASH_TIME_DIFFERENCE:
                # Check if the JIRA numbers are the same or if either commit does not have a JIRA number
                if commit_jira_number == current_jira_number or not commit_jira_number or not current_jira_number:
                    current_squash_group.append((current_commit, current_author))
                    current_jira_number = commit_jira_number or current_jira_number
                else:
                    # JIRA numbers are different, process the current group and start a new one
                    if len(current_squash_group) > 1:
                        start = current_squash_group[0][0]
                        end = current_squash_group[-1][0]
                        squash_commit_group(current_squash_group, start, end)
                        squashed_commits.append((current_squash_group, end))
                    current_squash_group = [(current_commit, current_author)]
                    current_jira_number = commit_jira_number
            else:
                # Process the current squash group if the next author is different or the time difference is too large
                if len(current_squash_group) > 1:
                    start = current_squash_group[0][0]
                    end = current_commit
                    squash_commit_group(current_squash_group, start, end)
                    squashed_commits.append((current_squash_group, end))
                current_squash_group = [(current_commit, current_author)]
                current_jira_number = None  # Reset the JIRA number
        else:
            # If it's the last commit in the list, add it to the current squash group
            current_squash_group.append((current_commit, current_author))

    # Process the last squash group if it has more than one commit
    if len(current_squash_group) > 1:
        start = current_squash_group[0][0]
        end = current_squash_group[-1][0]
        squash_commit_group(current_squash_group, start, end)
        squashed_commits.append((current_squash_group, end))

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
    try:
        branches = get_branches()

        for branch in branches:
            squash_commits(branch)

        print("Done squashing commits. Please review the changes before pushing.")
        print("If you're satisfied with the changes, you can push all branches to the new repository with:")
        print("git push --all <new-repo-url>")

    except Exception as e:
        logging.error("Script terminated due to an error. Please check the logs for details.")
        exit(1)  # Non-zero exit code to indicate failure


if __name__ == "__main__":
    main()
