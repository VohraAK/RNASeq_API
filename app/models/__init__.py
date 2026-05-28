# Import all models so SQLAlchemy's mapper registry is fully populated
# before any relationship resolution occurs.
from app.models.api_key import APIKey  # noqa: F401
from app.models.file import File  # noqa: F401
from app.models.job import Job  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.result import Result  # noqa: F401
from app.models.user import User  # noqa: F401
