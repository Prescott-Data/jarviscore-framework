"""Provider adapters that produce generic source snapshots."""

from .base import (
	SourceAdapter,
	SourceAdapterError,
	SourceContractError,
	SourceIntegrityError,
	capture_source,
)
from .github import (
	GitHubRepositorySource,
	GitHubSourceRequestError,
	SnapshotLimitExceeded,
	SnapshotLimits,
)

__all__ = [
	"GitHubRepositorySource",
	"GitHubSourceRequestError",
	"SnapshotLimitExceeded",
	"SnapshotLimits",
	"SourceAdapter",
	"SourceAdapterError",
	"SourceContractError",
	"SourceIntegrityError",
	"capture_source",
]