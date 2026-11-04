"""Stateless source importers and the CLI's supported-format registry."""

from pixi.interfaces.knowledge import KnowledgeImporter
from pixi.knowledge_import.devdocs import DevDocsImporter
from pixi.knowledge_import.kiwix import KiwixImporter
from pixi.knowledge_import.mediawiki import MediaWikiImporter

IMPORTERS: dict[str, KnowledgeImporter] = {
    "mediawiki": MediaWikiImporter(),
    "devdocs": DevDocsImporter(),
    "kiwix": KiwixImporter(),
}
