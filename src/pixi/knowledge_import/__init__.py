"""Stateless source importers and the CLI's supported-format registry."""

from ..interfaces.knowledge import KnowledgeImporter
from .devdocs import DevDocsImporter
from .kiwix import KiwixImporter
from .mediawiki import MediaWikiImporter


IMPORTERS: dict[str, KnowledgeImporter] = {
    "mediawiki": MediaWikiImporter(),
    "devdocs": DevDocsImporter(),
    "kiwix": KiwixImporter(),
}
