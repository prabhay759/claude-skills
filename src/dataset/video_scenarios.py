"""
Six screen-recording scenario templates for the video-to-skill benchmark.

Each scenario simulates a developer screen-recording session. A task variant
picks a subset of the scenario's 5 required steps as "active"; the transcript
generator weaves clear visual evidence for active steps and plausible
alternative actions for inactive ones.

Structure mirrors src/dataset/scenarios.py:
  SCENARIOS[name] = {
      "title":               str,
      "description":         str,
      "steps":               {step_key: {category, description, keywords}},
      "generate_transcript": callable(active_steps: set[str]) -> str,
  }
"""

from __future__ import annotations


# ─── scenario 1: git workflow ─────────────────────────────────────────────────

def _git_transcript(active: set[str]) -> str:
    frames: list[str] = [
        "[00:00] Developer opens a terminal. The shell prompt shows the project "
        "root directory: ~/projects/webapp.",
    ]

    if "git_status" in active:
        frames.append(
            "[00:08] Developer types: git status\n"
            "Output shows:\n"
            "  On branch feature/user-auth\n"
            "  Changes not staged for commit:\n"
            "    modified:   src/auth.py\n"
            "    modified:   tests/test_auth.py\n"
            "  Untracked files:\n"
            "    src/middleware.py\n"
            "Developer reads the working tree status before proceeding."
        )
    else:
        frames.append(
            "[00:08] Developer opens src/auth.py in the editor and scrolls "
            "through the recent changes they made."
        )

    if "stage_changes" in active:
        frames.append(
            "[00:22] Developer types: git add -p\n"
            "Git shows a hunk from src/auth.py with a password hashing change.\n"
            "Developer types 'y' to stage it.\n"
            "Next hunk appears — a debug print statement.\n"
            "Developer types 'n' to skip it.\n"
            "Developer types: git add src/middleware.py\n"
            "Selective staging complete; the debug print is intentionally excluded."
        )
    else:
        frames.append(
            "[00:22] Developer types: git add .\n"
            "All changes are staged at once."
        )

    if "commit_message" in active:
        frames.append(
            "[00:40] Developer types: git commit\n"
            "Editor opens. Developer writes:\n"
            "  feat(auth): add bcrypt password hashing and rate limiting\n"
            "  \n"
            "  - Replace MD5 with bcrypt (cost factor 12) for all password storage\n"
            "  - Add per-IP rate limiting middleware (10 req/min on /login)\n"
            "  - Update tests to mock bcrypt for speed\n"
            "Developer saves and closes the editor. Commit is created."
        )
    else:
        frames.append(
            "[00:40] Developer types: git commit -m 'wip auth changes'\n"
            "Quick commit message used."
        )

    if "push_branch" in active:
        frames.append(
            "[00:58] Developer types: git push -u origin feature/user-auth\n"
            "Output:\n"
            "  Enumerating objects: 9, done.\n"
            "  Counting objects: 100% (9/9), done.\n"
            "  Branch 'feature/user-auth' set up to track remote.\n"
            "Branch is pushed to the remote repository."
        )
    else:
        frames.append(
            "[00:58] Developer runs: git log --oneline -5\n"
            "Reviews the recent commit history."
        )

    if "open_pull_request" in active:
        frames.append(
            "[01:10] Developer switches to the browser. Navigates to GitHub repository.\n"
            "A yellow banner prompts: 'Compare & pull request' for the recently pushed branch.\n"
            "Developer clicks it. Fills in the PR title: 'feat(auth): bcrypt + rate limiting'.\n"
            "Adds a description referencing the issue number.\n"
            "Clicks 'Create pull request'. PR is created successfully."
        )
    else:
        frames.append(
            "[01:10] Developer opens the project README to check deployment notes."
        )

    frames.append(
        "[01:25] Recording ends. Terminal window visible with prompt."
    )

    return (
        "VIDEO TRANSCRIPT\n"
        "Scenario: Git feature branch workflow\n"
        "Duration: ~1.5 minutes\n"
        "Recording: Screen capture of a developer managing git changes\n"
        "\n"
        + "\n\n".join(frames)
    )


# ─── scenario 2: debug session ────────────────────────────────────────────────

def _debug_transcript(active: set[str]) -> str:
    frames: list[str] = [
        "[00:00] Developer has a Python project open. Terminal shows the project "
        "root. A test file is visible in the editor on the right.",
    ]

    if "run_failing_test" in active:
        frames.append(
            "[00:06] Developer types: pytest tests/test_processor.py -x\n"
            "Output:\n"
            "  FAILED tests/test_processor.py::test_calculate_total\n"
            "  AssertionError: assert 0 == 42\n"
            "  E   Where: 42 is the expected total\n"
            "1 failed in 0.34s\n"
            "The -x flag stops on first failure."
        )
    else:
        frames.append(
            "[00:06] Developer types: pytest tests/ -v\n"
            "All tests pass. Developer sees the green output."
        )

    if "read_traceback" in active:
        frames.append(
            "[00:18] Developer scrolls up in the terminal to read the full traceback.\n"
            "  File 'src/processor.py', line 47, in calculate_total\n"
            "    return sum(item.price for item in self.items)\n"
            "  AttributeError: 'NoneType' object has no attribute 'price'\n"
            "Developer reads the traceback carefully, identifying the line and "
            "the null reference as the root cause."
        )
    else:
        frames.append(
            "[00:18] Developer glances at the error and immediately starts typing "
            "in the source file."
        )

    if "set_breakpoint" in active:
        frames.append(
            "[00:32] Developer opens src/processor.py in the editor.\n"
            "Navigates to line 45, just before the calculate_total method.\n"
            "Types: import pdb; pdb.set_trace()\n"
            "Saves the file.\n"
            "Switches back to terminal and runs: pytest tests/test_processor.py::test_calculate_total -s\n"
            "Program halts at the pdb breakpoint. The (Pdb) prompt appears."
        )
    else:
        frames.append(
            "[00:32] Developer adds a print statement: print('items:', self.items)\n"
            "Saves and re-runs tests to see the output."
        )

    if "inspect_variable" in active:
        frames.append(
            "[00:48] At the pdb prompt, developer types: p self.items\n"
            "Output: [<Item id=1 price=10>, None, <Item id=3 price=32>]\n"
            "Developer types: pp [type(i) for i in self.items]\n"
            "Output: [<class 'Item'>, <class 'NoneType'>, <class 'Item'>]\n"
            "The None value in the list is confirmed as the cause."
        )
    else:
        frames.append(
            "[00:48] Developer reads the print output and identifies the "
            "problematic value in the terminal."
        )

    if "fix_and_verify" in active:
        frames.append(
            "[01:05] Developer types 'c' at the pdb prompt to continue execution.\n"
            "Removes the pdb line from the source file.\n"
            "Edits calculate_total to filter None values:\n"
            "  return sum(item.price for item in self.items if item is not None)\n"
            "Saves the file.\n"
            "Runs: pytest tests/test_processor.py -x\n"
            "Output: 1 passed in 0.31s\n"
            "Test passes. Developer confirms the fix is correct."
        )
    else:
        frames.append(
            "[01:05] Developer notes the issue and opens a new GitHub issue "
            "to track the bug."
        )

    frames.append(
        "[01:20] Recording ends. Terminal shows the final test run result."
    )

    return (
        "VIDEO TRANSCRIPT\n"
        "Scenario: Python debugging session with pdb\n"
        "Duration: ~1.5 minutes\n"
        "Recording: Screen capture of a developer debugging a failing test\n"
        "\n"
        + "\n\n".join(frames)
    )


# ─── scenario 3: deployment workflow ─────────────────────────────────────────

def _deploy_transcript(active: set[str]) -> str:
    frames: list[str] = [
        "[00:00] Developer has a terminal open. The project directory contains "
        "a Dockerfile and a docker-compose.yml. CI just passed on the main branch.",
    ]

    if "docker_build" in active:
        frames.append(
            "[00:09] Developer types: docker build -t myapp:v2.3.1 .\n"
            "Docker begins building. Output shows each layer being processed.\n"
            "Several layers are cached (CACHED).\n"
            "Final line: Successfully built a3f9c2b1d4e5\n"
            "Successfully tagged myapp:v2.3.1\n"
            "Build completes in 23 seconds."
        )
    else:
        frames.append(
            "[00:09] Developer runs: docker images\n"
            "Reviews the list of existing local images."
        )

    if "run_tests_container" in active:
        frames.append(
            "[00:38] Developer types: docker run --rm myapp:v2.3.1 pytest tests/ -q\n"
            "Container starts. Pytest runs inside the container.\n"
            "Output:\n"
            "  ...........\n"
            "  47 passed in 8.12s\n"
            "Tests pass inside the container environment. Developer is satisfied."
        )
    else:
        frames.append(
            "[00:38] Developer checks the CI test results on the GitHub Actions page."
        )

    if "docker_push" in active:
        frames.append(
            "[00:55] Developer types: docker tag myapp:v2.3.1 registry.example.com/myapp:v2.3.1\n"
            "Then: docker push registry.example.com/myapp:v2.3.1\n"
            "Output shows each layer being pushed:\n"
            "  v2.3.1: digest: sha256:abc123... size: 42MB\n"
            "Image is pushed to the container registry."
        )
    else:
        frames.append(
            "[00:55] Developer opens the registry web UI to check existing image tags."
        )

    if "ssh_server" in active:
        frames.append(
            "[01:12] Developer types: ssh deploy@prod-server-01.example.com\n"
            "SSH handshake. Shell prompt changes to: deploy@prod-server-01:~$\n"
            "Developer is now on the production server."
        )
    else:
        frames.append(
            "[01:12] Developer opens a Slack channel to notify the team of the "
            "upcoming deploy."
        )

    if "restart_service" in active:
        frames.append(
            "[01:20] On the production server, developer types:\n"
            "  docker pull registry.example.com/myapp:v2.3.1\n"
            "Image is pulled. Then:\n"
            "  docker-compose up -d --no-deps app\n"
            "Container is replaced with zero-downtime restart.\n"
            "Developer runs: docker ps | grep myapp\n"
            "New container shows status 'Up 5 seconds'. Service is running."
        )
    else:
        frames.append(
            "[01:20] Developer checks the server health endpoint via curl: "
            "curl http://prod-server-01/health"
        )

    frames.append(
        "[01:45] Recording ends. Terminal shows the production server prompt."
    )

    return (
        "VIDEO TRANSCRIPT\n"
        "Scenario: Docker build and production deployment\n"
        "Duration: ~1.75 minutes\n"
        "Recording: Screen capture of a developer deploying a containerised app\n"
        "\n"
        + "\n\n".join(frames)
    )


# ─── scenario 4: data analysis ────────────────────────────────────────────────

def _data_transcript(active: set[str]) -> str:
    frames: list[str] = [
        "[00:00] Developer opens a Jupyter notebook. The notebook is titled "
        "'sales_data_analysis.ipynb'. A CSV file is visible in the file browser.",
    ]

    if "load_data" in active:
        frames.append(
            "[00:08] Developer adds a new cell and types:\n"
            "  import pandas as pd\n"
            "  df = pd.read_csv('data/sales_2026.csv')\n"
            "  print(f'Loaded {len(df)} rows')\n"
            "Runs the cell. Output: Loaded 15420 rows\n"
            "Data is loaded into a pandas DataFrame."
        )
    else:
        frames.append(
            "[00:08] Developer opens the CSV file directly in the file browser "
            "and glances at the first few lines."
        )

    if "explore_data" in active:
        frames.append(
            "[00:20] Developer adds a cell: df.head()\n"
            "Output shows the first 5 rows with columns: date, region, product, quantity, revenue.\n"
            "Next cell: df.info()\n"
            "Output shows dtypes and non-null counts. Column 'revenue' has 14890 non-null (530 missing).\n"
            "Next cell: df.describe()\n"
            "Summary statistics for numeric columns are displayed."
        )
    else:
        frames.append(
            "[00:20] Developer looks at the data dictionary document in the browser."
        )

    if "handle_missing" in active:
        frames.append(
            "[00:38] Developer types: df.isna().sum()\n"
            "Output shows revenue: 530, all others: 0.\n"
            "Developer adds a cell:\n"
            "  df['revenue'] = df['revenue'].fillna(df['revenue'].median())\n"
            "  print('Missing values after fill:', df.isna().sum().sum())\n"
            "Output: Missing values after fill: 0\n"
            "Missing revenue values are filled with the median."
        )
    else:
        frames.append(
            "[00:38] Developer notes the missing values and adds a comment in "
            "the notebook but continues without handling them."
        )

    if "filter_transform" in active:
        frames.append(
            "[00:55] Developer adds cells to filter and transform the data:\n"
            "  q4 = df[df['date'].str.startswith('2026-1')]\n"
            "  q4['revenue_k'] = q4['revenue'] / 1000\n"
            "  top_regions = q4.groupby('region')['revenue'].sum().nlargest(5)\n"
            "  print(top_regions)\n"
            "Output shows the top 5 regions by Q4 revenue. Developer filters the "
            "data to Q4 and creates a revenue-in-thousands column."
        )
    else:
        frames.append(
            "[00:55] Developer aggregates the full dataset without filtering: "
            "df.groupby('region')['revenue'].sum()"
        )

    if "visualize_export" in active:
        frames.append(
            "[01:15] Developer adds visualization cells:\n"
            "  import matplotlib.pyplot as plt\n"
            "  top_regions.plot(kind='bar', title='Top 5 Regions Q4 2026')\n"
            "  plt.tight_layout()\n"
            "  plt.savefig('output/q4_top_regions.png', dpi=150)\n"
            "  plt.show()\n"
            "Bar chart appears in the notebook output.\n"
            "Then: q4.to_csv('output/q4_cleaned.csv', index=False)\n"
            "Developer exports the cleaned and filtered data to CSV."
        )
    else:
        frames.append(
            "[01:15] Developer prints summary numbers to the notebook cell output."
        )

    frames.append(
        "[01:35] Recording ends. Jupyter notebook shows completed cells."
    )

    return (
        "VIDEO TRANSCRIPT\n"
        "Scenario: Jupyter notebook data analysis with pandas\n"
        "Duration: ~1.6 minutes\n"
        "Recording: Screen capture of a developer analyzing sales data\n"
        "\n"
        + "\n\n".join(frames)
    )


# ─── scenario 5: api testing ──────────────────────────────────────────────────

def _api_transcript(active: set[str]) -> str:
    frames: list[str] = [
        "[00:00] Developer has a terminal open alongside a text editor showing "
        "a FastAPI application. The API is not yet running.",
    ]

    if "check_server" in active:
        frames.append(
            "[00:07] Developer types: curl http://localhost:8000/health\n"
            "Error: curl: (7) Failed to connect to localhost port 8000\n"
            "Developer starts the server: uvicorn main:app --reload\n"
            "Server starts. Log shows: Application startup complete.\n"
            "Developer opens a second terminal and types: curl http://localhost:8000/health\n"
            "Response: {\"status\": \"ok\", \"version\": \"1.4.2\"}"
        )
    else:
        frames.append(
            "[00:07] Developer assumes the server is already running and opens "
            "a browser tab to http://localhost:8000/docs to view the API docs."
        )

    if "craft_request" in active:
        frames.append(
            "[00:22] Developer composes a POST request in the terminal:\n"
            "  curl -X POST http://localhost:8000/api/orders \\\n"
            "    -H 'Content-Type: application/json' \\\n"
            "    -H 'Authorization: Bearer test-token-123' \\\n"
            "    -d '{\"product_id\": 42, \"quantity\": 3}'\n"
            "Developer carefully sets the Content-Type header and auth token "
            "before sending the request."
        )
    else:
        frames.append(
            "[00:22] Developer uses the Swagger UI at /docs to test the endpoint "
            "by clicking 'Try it out'."
        )

    if "inspect_response" in active:
        frames.append(
            "[00:38] API returns a JSON response:\n"
            "  {\n"
            "    \"order_id\": \"ord_8fa3b2\",\n"
            "    \"status\": \"pending\",\n"
            "    \"total\": 89.97,\n"
            "    \"estimated_delivery\": \"2026-06-10\"\n"
            "  }\n"
            "Developer inspects the JSON response and pipes it through jq for "
            "pretty-printing: | jq .\n"
            "Confirms the order_id, status, and total fields are correct."
        )
    else:
        frames.append(
            "[00:38] Developer sees a 200 OK status and moves on without "
            "examining the response body closely."
        )

    if "test_error_case" in active:
        frames.append(
            "[00:52] Developer tests an error case — sending an invalid quantity:\n"
            "  curl -X POST http://localhost:8000/api/orders \\\n"
            "    -H 'Content-Type: application/json' \\\n"
            "    -H 'Authorization: Bearer test-token-123' \\\n"
            "    -d '{\"product_id\": 42, \"quantity\": -1}' -i\n"
            "Response headers show HTTP/1.1 422 Unprocessable Entity.\n"
            "Body: {\"detail\": [{\"loc\": [\"body\", \"quantity\"], "
            "\"msg\": \"quantity must be positive\"}]}\n"
            "Developer confirms the error case returns the correct 422 status."
        )
    else:
        frames.append(
            "[00:52] Developer sends a second valid request to test idempotency."
        )

    if "check_logs" in active:
        frames.append(
            "[01:08] Developer switches to the terminal running uvicorn.\n"
            "Server logs show:\n"
            "  INFO: POST /api/orders HTTP/1.1 201 Created\n"
            "  INFO: POST /api/orders HTTP/1.1 422 Unprocessable Entity\n"
            "Developer reads the access logs to confirm both requests were "
            "processed and logged with the correct HTTP status codes."
        )
    else:
        frames.append(
            "[01:08] Developer opens the database admin panel to verify the "
            "order record was created."
        )

    frames.append(
        "[01:25] Recording ends. Terminal shows the uvicorn server still running."
    )

    return (
        "VIDEO TRANSCRIPT\n"
        "Scenario: REST API testing with curl\n"
        "Duration: ~1.4 minutes\n"
        "Recording: Screen capture of a developer testing a FastAPI endpoint\n"
        "\n"
        + "\n\n".join(frames)
    )


# ─── scenario 6: environment setup ───────────────────────────────────────────

def _env_transcript(active: set[str]) -> str:
    frames: list[str] = [
        "[00:00] Developer opens a terminal in their home directory. "
        "They have just cloned a new Python project repository.",
    ]

    if "create_virtualenv" in active:
        frames.append(
            "[00:09] Developer types: cd myproject\n"
            "Then: python -m venv .venv\n"
            "The virtual environment is created in the .venv directory.\n"
            "Developer can see the .venv folder appear in the file browser."
        )
    else:
        frames.append(
            "[00:09] Developer navigates into the project: cd myproject\n"
            "Uses the system Python without a virtual environment."
        )

    if "activate_env" in active:
        frames.append(
            "[00:20] Developer types: source .venv/bin/activate\n"
            "The shell prompt changes to show (.venv) prefix:\n"
            "  (.venv) user@machine:~/myproject$\n"
            "The virtual environment is now active."
        )
    else:
        frames.append(
            "[00:20] Developer skips activation and proceeds with the system Python."
        )

    if "install_deps" in active:
        frames.append(
            "[00:28] Developer types: pip install -r requirements.txt\n"
            "Pip begins downloading and installing packages.\n"
            "Output shows each package being installed:\n"
            "  Collecting fastapi==0.100.0\n"
            "  Collecting sqlalchemy==2.0.1\n"
            "  ...\n"
            "  Successfully installed 23 packages\n"
            "All project dependencies are installed."
        )
    else:
        frames.append(
            "[00:28] Developer manually installs one package: pip install fastapi"
        )

    if "configure_env_vars" in active:
        frames.append(
            "[00:52] Developer types: cp .env.example .env\n"
            "Opens .env in the editor.\n"
            "Fills in the following values:\n"
            "  DATABASE_URL=postgresql://user:pass@localhost/myapp_dev\n"
            "  SECRET_KEY=dev-secret-key-change-in-prod\n"
            "  DEBUG=true\n"
            "Saves the file. Environment variables are configured for local development."
        )
    else:
        frames.append(
            "[00:52] Developer notes that .env.example exists but continues without "
            "copying or configuring it."
        )

    if "verify_setup" in active:
        frames.append(
            "[01:10] Developer types: python -c \"from src import app; print('Import OK')\"\n"
            "Output: Import OK\n"
            "Then runs: pytest tests/ -q --tb=short\n"
            "Output:\n"
            "  ................\n"
            "  16 passed in 2.14s\n"
            "All tests pass. The environment setup is complete and verified."
        )
    else:
        frames.append(
            "[01:10] Developer opens the editor and starts reading the source code "
            "without verifying the setup."
        )

    frames.append(
        "[01:30] Recording ends. Terminal shows the active virtual environment prompt."
    )

    return (
        "VIDEO TRANSCRIPT\n"
        "Scenario: Python development environment setup\n"
        "Duration: ~1.5 minutes\n"
        "Recording: Screen capture of a developer setting up a project from scratch\n"
        "\n"
        + "\n\n".join(frames)
    )


# ─── scenarios registry ───────────────────────────────────────────────────────

SCENARIOS: dict[str, dict] = {
    "git_workflow": {
        "title": "Recording: Git feature branch workflow",
        "description": (
            "A developer manages changes on a feature branch — checking status, "
            "staging selectively, writing a commit message, pushing to the remote, "
            "and opening a pull request."
        ),
        "generate_transcript": _git_transcript,
        "steps": {
            "git_status": {
                "category": "version_control",
                "description": "Check working tree status before staging",
                "keywords": ["git status", "working tree", "untracked", "modified", "check status"],
            },
            "stage_changes": {
                "category": "version_control",
                "description": "Selectively stage changes using git add -p",
                "keywords": ["git add -p", "patch", "stage", "hunk", "selective staging", "add -p"],
            },
            "commit_message": {
                "category": "version_control",
                "description": "Write a descriptive multi-line commit message",
                "keywords": ["commit message", "git commit", "descriptive", "commit body", "conventional commit"],
            },
            "push_branch": {
                "category": "version_control",
                "description": "Push the branch to the remote repository",
                "keywords": ["git push", "push", "remote", "upstream", "origin"],
            },
            "open_pull_request": {
                "category": "collaboration",
                "description": "Open a pull request on GitHub",
                "keywords": ["pull request", "PR", "GitHub", "create PR", "open PR", "compare & pull request"],
            },
        },
    },

    "debug_session": {
        "title": "Recording: Python debugging session with pdb",
        "description": (
            "A developer debugs a failing pytest test by reading the traceback, "
            "setting a pdb breakpoint, inspecting variables at runtime, and "
            "applying a fix."
        ),
        "generate_transcript": _debug_transcript,
        "steps": {
            "run_failing_test": {
                "category": "testing",
                "description": "Run pytest to reproduce the failing test",
                "keywords": ["pytest", "failing test", "run test", "test failure", "pytest -x"],
            },
            "read_traceback": {
                "category": "debugging",
                "description": "Read and understand the traceback to identify root cause",
                "keywords": ["traceback", "read traceback", "error message", "AttributeError", "root cause", "line number"],
            },
            "set_breakpoint": {
                "category": "debugging",
                "description": "Set a pdb breakpoint to pause execution",
                "keywords": ["pdb", "breakpoint", "set_trace", "pdb.set_trace", "pause execution", "import pdb"],
            },
            "inspect_variable": {
                "category": "debugging",
                "description": "Inspect variable values at the pdb prompt",
                "keywords": ["pdb prompt", "inspect variable", "p variable", "pp", "Pdb", "print value"],
            },
            "fix_and_verify": {
                "category": "testing",
                "description": "Apply the fix and re-run tests to verify",
                "keywords": ["fix", "verify", "re-run", "test pass", "green", "confirm", "1 passed"],
            },
        },
    },

    "deploy_workflow": {
        "title": "Recording: Docker build and production deployment",
        "description": (
            "A developer builds a Docker image, runs tests inside the container, "
            "pushes to a registry, SSHes into a server, and restarts the service."
        ),
        "generate_transcript": _deploy_transcript,
        "steps": {
            "docker_build": {
                "category": "containerization",
                "description": "Build a Docker image with a version tag",
                "keywords": ["docker build", "docker image", "Dockerfile", "build image", "successfully built"],
            },
            "run_tests_container": {
                "category": "testing",
                "description": "Run tests inside the Docker container to validate the build",
                "keywords": ["docker run", "tests in container", "container test", "pytest in docker", "--rm"],
            },
            "docker_push": {
                "category": "containerization",
                "description": "Push the image to a container registry",
                "keywords": ["docker push", "push image", "registry", "docker tag", "container registry"],
            },
            "ssh_server": {
                "category": "deployment",
                "description": "SSH into the production server",
                "keywords": ["ssh", "production server", "remote server", "SSH into", "deploy@"],
            },
            "restart_service": {
                "category": "deployment",
                "description": "Pull the new image and restart the service",
                "keywords": ["docker pull", "restart", "docker-compose up", "zero-downtime", "service restart", "docker ps"],
            },
        },
    },

    "data_analysis": {
        "title": "Recording: Jupyter notebook data analysis with pandas",
        "description": (
            "A developer loads a CSV dataset, explores its structure, handles "
            "missing values, filters and transforms the data, then visualizes "
            "and exports the results."
        ),
        "generate_transcript": _data_transcript,
        "steps": {
            "load_data": {
                "category": "data_ingestion",
                "description": "Load CSV data into a pandas DataFrame",
                "keywords": ["pd.read_csv", "load data", "DataFrame", "read_csv", "import pandas"],
            },
            "explore_data": {
                "category": "data_exploration",
                "description": "Explore the dataset shape, types, and statistics",
                "keywords": ["df.head", "df.info", "df.describe", "explore", "summary statistics", "data types"],
            },
            "handle_missing": {
                "category": "data_cleaning",
                "description": "Identify and handle missing values",
                "keywords": ["missing values", "fillna", "dropna", "isna", "null values", "handle missing"],
            },
            "filter_transform": {
                "category": "data_transformation",
                "description": "Filter rows and transform columns",
                "keywords": ["filter", "transform", "groupby", "apply", "column transformation", "subset"],
            },
            "visualize_export": {
                "category": "output",
                "description": "Create a visualization and export cleaned data",
                "keywords": ["plot", "matplotlib", "visualize", "to_csv", "export", "savefig", "chart"],
            },
        },
    },

    "api_testing": {
        "title": "Recording: REST API testing with curl",
        "description": (
            "A developer verifies a FastAPI server is running, crafts a curl POST "
            "request with auth headers, inspects the JSON response, tests an error "
            "case, and checks server logs."
        ),
        "generate_transcript": _api_transcript,
        "steps": {
            "check_server": {
                "category": "setup",
                "description": "Verify the API server is running and reachable",
                "keywords": ["server running", "health check", "curl /health", "startup", "application startup", "check server"],
            },
            "craft_request": {
                "category": "api_testing",
                "description": "Compose a curl request with headers and JSON body",
                "keywords": ["curl", "POST request", "Content-Type", "Authorization", "request body", "header"],
            },
            "inspect_response": {
                "category": "api_testing",
                "description": "Inspect and verify the JSON response fields",
                "keywords": ["JSON response", "inspect response", "response body", "jq", "verify response", "response fields"],
            },
            "test_error_case": {
                "category": "api_testing",
                "description": "Test an invalid input to verify error handling",
                "keywords": ["error case", "422", "error handling", "invalid input", "error response", "status code"],
            },
            "check_logs": {
                "category": "observability",
                "description": "Check server access logs to confirm requests were logged",
                "keywords": ["server logs", "access log", "uvicorn", "log output", "HTTP status", "check logs"],
            },
        },
    },

    "env_setup": {
        "title": "Recording: Python development environment setup",
        "description": (
            "A developer sets up a Python project from scratch by creating a "
            "virtual environment, activating it, installing dependencies, "
            "configuring environment variables, and verifying the setup."
        ),
        "generate_transcript": _env_transcript,
        "steps": {
            "create_virtualenv": {
                "category": "environment",
                "description": "Create a Python virtual environment",
                "keywords": ["venv", "virtualenv", "python -m venv", "create virtual environment", ".venv"],
            },
            "activate_env": {
                "category": "environment",
                "description": "Activate the virtual environment",
                "keywords": ["activate", "source .venv", "activate virtual environment", "(.venv)", "venv activate"],
            },
            "install_deps": {
                "category": "dependencies",
                "description": "Install project dependencies from requirements.txt",
                "keywords": ["pip install", "requirements.txt", "install dependencies", "pip install -r", "packages installed"],
            },
            "configure_env_vars": {
                "category": "configuration",
                "description": "Copy and configure the .env file with local settings",
                "keywords": ["environment variables", ".env", "env vars", "DATABASE_URL", "SECRET_KEY", "configure"],
            },
            "verify_setup": {
                "category": "verification",
                "description": "Run a smoke test to confirm the environment works",
                "keywords": ["verify", "smoke test", "pytest", "import OK", "tests pass", "setup complete"],
            },
        },
    },
}
