# Contributing to Voyager 2 Reminder

Thank you for your interest in contributing to the Voyager 2 Reminder project! 🚀

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/yourusername/voyager2-reminder.git
   cd voyager2-reminder
   ```
3. **Set up the development environment** following the instructions in the README

## Development Process

### 1. Create a Branch
```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-description
```

### 2. Development Guidelines

#### Code Style
- Follow PEP 8 for Python code
- Use meaningful variable and function names
- Add docstrings to functions and classes
- Keep functions small and focused

#### Code Formatting
We use automated code formatting tools:
```bash
# Install formatting tools
pip install black isort flake8

# Format code
black .
isort .

# Check linting
flake8 app/ --max-line-length=88 --extend-ignore=E203,W503
```

#### Testing
- Write tests for new features
- Ensure all tests pass before submitting
- Aim for good test coverage

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=app
```

### 3. Commit Messages
Use clear, descriptive commit messages:
```
feat: add support for light-year distance units
fix: resolve email delivery timeout issue
docs: update API documentation
test: add tests for user registration
```

### 4. Pull Request Process

1. **Update documentation** if needed
2. **Add tests** for new functionality
3. **Ensure CI passes** (linting, tests, Docker build)
4. **Update CHANGELOG.md** if applicable
5. **Submit the pull request**

#### Pull Request Template
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tests added/updated
- [ ] All tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
```

## Types of Contributions

### 🐛 Bug Reports
- Use the issue template
- Include steps to reproduce
- Provide system information
- Include error messages/logs

### ✨ Feature Requests
- Describe the feature clearly
- Explain the use case
- Consider implementation approach
- Discuss potential alternatives

### 📖 Documentation
- Fix typos and grammar
- Improve clarity
- Add examples
- Update outdated information

### 🔧 Code Contributions
- Bug fixes
- New features
- Performance improvements
- Refactoring

## Development Environment

### Prerequisites
- Python 3.11+
- Docker (optional)
- Git

### Setup
```bash
# Clone and navigate
git clone https://github.com/yourusername/voyager2-reminder.git
cd voyager2-reminder

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install pytest black isort flake8

# Copy environment file
cp env.example .env
# Edit .env with your configuration

# Run the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

## Project Structure

```
voyager2-reminder/
├── app/                    # Main application package
│   ├── main.py            # FastAPI app and routes
│   ├── models.py          # Database models
│   ├── database.py        # Database configuration
│   ├── scheduler.py       # Background scheduler
│   ├── emailer.py         # Email functionality
│   └── distance_fetcher.py # Voyager 2 API client
├── tests/                 # Test files
├── docs/                  # Documentation
├── .github/               # GitHub workflows
└── data/                  # Database files (gitignored)
```

## Code Review Guidelines

### For Reviewers
- Be constructive and respectful
- Focus on code quality and maintainability
- Check for security issues
- Verify tests are adequate
- Test the changes locally if possible

### For Contributors
- Respond to feedback promptly
- Make requested changes
- Ask questions if unclear
- Be open to suggestions

## Release Process

1. **Update version** in relevant files
2. **Update CHANGELOG.md**
3. **Create release PR**
4. **Tag release** after merge
5. **Deploy to production**

## Getting Help

- **GitHub Issues**: For bugs and feature requests
- **Discussions**: For questions and general discussion
- **Documentation**: Check the README and docs/ folder

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Focus on what's best for the community
- Show empathy towards others

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to Voyager 2 Reminder! 🌟 