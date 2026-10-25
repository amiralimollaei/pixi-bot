import asyncio
from glob import glob

from pixi.storage.knowledge import DocumentCollection, KnowledgeBase
from pixi.storage.knowledge_disk import KnowledgeDiskStorage
from pixi.storage.paths import PixiPaths


async def main():
    # Create and save a named knowledge base.
    storage = KnowledgeDiskStorage(PixiPaths.knowledge())

    documents = DocumentCollection()
    for file in glob("path/to/files/**/*.md"):
        content = open(file, "r", encoding="utf-8").read()
        documents.add_document(
            title=f"EntryTitle ({file})", text=content, source="EntrySource"
        )
    KnowledgeBase("ExampleKnowledge", storage=storage, documents=documents).save()

    # Load the snapshot and query it.
    knowledge_base = KnowledgeBase.from_storage("ExampleKnowledge", storage)
    matches = await knowledge_base.search("quasi-connectivity")
    for match in matches:
        print(match)


if __name__ == "__main__":
    asyncio.run(main())
