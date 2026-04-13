from app.utils.db import init_schema
from app.utils.indexer import run_indexer
init_schema()
print(f'Indexed {run_indexer()} new entries')