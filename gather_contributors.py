import subprocess


def run_git_command(command):
    """Run a git command and return its output."""
    process = subprocess.run(['git'] + command, capture_output=True, text=True)
    if process.returncode != 0:
        raise Exception(f"Git command failed: {' '.join(command)}\n{process.stderr}")
    return process.stdout.strip()


def get_contributors():
    """Get a set of all unique contributors."""
    log_output = run_git_command(['log', '--format=%an <%ae>'])
    contributors = set()
    for line in log_output.split('\n'):
        name, email = line.split(' <')
        email = email[:-1]  # remove trailing '>'
        contributors.add((name, email))
    return contributors


def main():
    contributors = get_contributors()
    for contributor in contributors:
        print(contributor)


if __name__ == "__main__":
    main()
