"""Import-time configuration for the offline backend unit suite.

Set these before test modules import auth/database, including isolated file
runs. Tests supply SQLite or fake sessions; the unused default engine points to
a closed local port instead of inheriting a deployment database or signing key.
"""

import os

os.environ["JWT_SECRET_KEY"] = "backend-unit-tests-only-signing-key-32-characters"
os.environ["DATABASE_URL"] = "postgresql://unit_test:unit_test@127.0.0.1:1/unit_test"
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
