"""Database access facade.

Keep this module as the stable import path while the implementation lives in
services.database.
"""

from services.database import (
    database_stats,
    execute_insert,
    execute_many,
    execute_query,
    execute_update,
    get_connection,
    get_pool,
    reset_database_stats,
    reset_pool,
    transaction,
)
