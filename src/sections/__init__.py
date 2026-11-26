"""Section registry, in execution order."""
from __future__ import annotations

from typing import Dict, List, Type

from .base import RunContext, Section
from .content import ContentSection
from .followers import FollowersSection
from .life_page import LifePageSection
from .overview import OverviewSection
from .posts import PostsSection
from .search_appearances import SearchAppearancesSection
from .visitors import VisitorsSection

# order matters: content caches the post table for `posts`,
# visitors caches the page-views table for `life_page`.
ORDER: List[Type[Section]] = [
    OverviewSection,
    ContentSection,
    VisitorsSection,
    LifePageSection,
    FollowersSection,
    SearchAppearancesSection,
    PostsSection,
]

REGISTRY: Dict[str, Type[Section]] = {cls.key: cls for cls in ORDER}

__all__ = ["ORDER", "REGISTRY", "RunContext", "Section"]
