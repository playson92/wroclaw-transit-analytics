# Portfolio Project Template

Reusable template for data analytics, data engineering and Python application projects.

## Purpose

This repository provides a common structure for personal portfolio projects covering:

- data analysis,
- Python development,
- SQL development,
- data pipelines,
- relational databases,
- Docker,
- automated testing,
- documentation,
- GitHub Actions.

## Project structure

```text
.
├── .github/workflows/   # GitHub Actions workflows
├── data/
│   ├── processed/       # Locally processed data
│   ├── raw/             # Locally downloaded source data
│   └── sample/          # Small public example datasets
├── docker/              # Additional Docker configuration
├── docs/                # Architecture and project documentation
├── scripts/             # Utility and maintenance scripts
├── sql/                 # SQL queries and transformations
├── src/                 # Application source code
└── tests/               # Automated tests
```

## Planned tooling

- Python
- SQL
- PostgreSQL
- MySQL
- Microsoft SQL Server
- Docker and Docker Compose
- pytest
- GitHub Actions

Individual projects created from this template may use only part of this technology stack.

## Local development

Detailed setup instructions will be added when the first project is created from this template.

## Security

Do not commit:

- passwords,
- API keys,
- private certificates,
- `.env` files,
- confidential datasets,
- company source code or company data.

Use `.env.example` to document required environment variables without exposing their real values.

## Author

Jonatan Tomaszewicz

Data Analyst & Analytics Developer
