# Contributing to AI DLP Proxy

First off, thanks for taking the time to contribute! ❤️

All types of contributions are encouraged and valued. See the [Table of Contents](#table-of-contents) for different ways to help and details about how this project handles them.

## Table of Contents

- [I Have a Question](#i-have-a-question)
- [I Want To Contribute](#i-want-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Your First Code Contribution](#your-first-code-contribution)
- [Styleguides](#styleguides)
  - [Commit Messages](#commit-messages)

## I Have a Question

> If you want to ask a question, we assume that you have read the available [Documentation](index.md).

Before you ask a question, it is best to search for existing [Issues](https://github.com/fabriziosalmi/aidlp/issues) that might help you. In case you've found a suitable issue and still need clarification, you can write your question in this issue. It is also advisable to search the internet for answers first.

## I Want To Contribute

### Reporting Bugs

- **Ensure the bug was not already reported** by searching on GitHub under [Issues](https://github.com/fabriziosalmi/aidlp/issues).
- If you're unable to find an open issue addressing the problem, [open a new one](https://github.com/fabriziosalmi/aidlp/issues/new). Be sure to include a **title and clear description**, as much relevant information as possible, and a **code sample** or an **executable test case** demonstrating the expected behavior that is not occurring.

### Suggesting Enhancements

- Open a new issue with the label `enhancement`.
- Explain why this enhancement would be useful to most users.

### Your First Code Contribution

1.  **Fork the repository** on GitHub.
2.  **Clone your fork** locally.
3.  **Set up the environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    pip install pre-commit
    pre-commit install
    python -m spacy download en_core_web_lg
    ```
4.  **Create a branch** for your changes.
5.  **Make your changes**.
6.  **Run tests** to ensure nothing is broken:
    ```bash
    export PYTHONPATH=$PYTHONPATH:$(pwd)
    pytest tests/
    ```
7.  **Commit your changes** (see [Commit Messages](#commit-messages)).
8.  **Push to your fork** and submit a **Pull Request**.

## Styleguides

### Code Style

- We use **flake8** for linting.
- Run `flake8 .` before committing.
- Pre-commit hooks are configured to automatically check for linting errors.

### Commit Messages

- Use the present tense ("Add feature" not "Added feature").
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...").
- Limit the first line to 72 characters or less.
- Reference issues and pull requests liberally after the first line.
