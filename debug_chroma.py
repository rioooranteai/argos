import chromadb

client = chromadb.PersistentClient(path="./chroma_db")

for col in client.list_collections():
    collection = client.get_collection(col.name)
    print(f"\n{'='*60}")
    print(f"Collection: {col.name} | Total: {collection.count()} dokumen")
    print(f"{'='*60}")

    result = collection.get(
        include=["documents", "metadatas", "embeddings"]
    )

    for i, (doc_id, document, metadata, embedding) in enumerate(zip(
            result["ids"],
            result["documents"],
            result["metadatas"],
            result["embeddings"]
    )):
        print(f"[Chunk {i + 1}]")
        print(f"  Text     : {document}")
        print(f"  Metadata : {metadata}")
        print(f"  Embedding: {embedding}... (dim: {len(embedding)})")