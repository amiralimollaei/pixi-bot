import asyncio
from glob import glob

from pixi.database import DirectoryDatabase, DocumentDataset


async def main():
    # create and save a directory database

    dataset = DocumentDataset()
    for file in glob("path/to/files/**/*.md"):
        content = open(file, "r", encoding="utf-8").read()
        dataset.add_entry(
            title=f"EntryTitle ({file})",
            text=content,
            source="EntrySource"
        )
    await DirectoryDatabase("DatasetName", dataset=dataset).save()

    # load a directory database and query from it

    database = await DirectoryDatabase.from_directory("DatasetName")
    matches = await database.search("quasi-connectivity")
    for match in matches:
        print(match)

if __name__ == "__main__":
    asyncio.run(main())
