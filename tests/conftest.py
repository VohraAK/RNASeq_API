import os

# Set before any app.* imports so pydantic-settings picks them up at class-creation time.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaa1")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("UPLOAD_DIR", "/tmp/rnaseq_uploads_test")
