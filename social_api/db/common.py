from sqlalchemy import select
import typing
from sqlalchemy import Table
from sqlalchemy.sql.selectable import Select
from .base import database, STD_NUMBER_OF_RESULT_AT_A_TIME


async def fetch_one_record_filter_by_one_field(
    table: Table = None,
    filterField: str = '',
    filterValue: typing.Any = None
) -> typing.Union[None, typing.Mapping]:
    """
        fetch at most one record based on provided arguments\n
        if not found, returns None.\n
        NOTE: to have filterField, you must refer to table model definition in model.py files
    """
    query: Select = select([table]).where(
        table.c[filterField] == filterValue
    )
    return await database.fetch_one(query=query)


async def fetch_multiple_records(
    table: Table,
    filterField: str = None,
    filterValue: typing.Any = None,
    offset: int = 0,
    limit: int = STD_NUMBER_OF_RESULT_AT_A_TIME
) -> typing.Union[None, typing.List[typing.Mapping]]:
    """
        fetch multiple records from table then returns them\n
        If not found, returns None.\n
        limit is default set to 10.\n
        NOTE: to have filterField, you must refer to table model definition in model.py files
    """
    # incase not offset or offset equal to 0 provided
    if offset is None:
        raise ValueError('offset must be an integer.')
        return None

    # if 'filterField' and 'filterValue' were provided:
    query: Select = None
    if bool(filterField and filterValue):
        query = select([table]).where(
            table.c[filterField] == filterValue
        ).limit(limit).offset(offset)
    else:
        query = select([table]).limit(limit).offset(offset)

    return await database.fetch_all(query=query)


async def fetch_one_record_with_query(
    query: Select,
) -> typing.Union[None, typing.Mapping]:
    """
    fetch one record from database, bases on query provided
    """
    return await database.fetch_one(query=query)


async def fetch_multiple_records_with_query(
    query: Select,
    offset: int = 0,
    limit: int = STD_NUMBER_OF_RESULT_AT_A_TIME
) -> typing.Union[None, typing.Mapping]:
    """
    fetch multiple records from database, bases on query provided
    """
    if offset is None:
        raise ValueError('offset must be an integer.')
        return None
    query = query.limit(limit=limit).offset(offset)
    return await database.fetch_all(query=query)


async def execute_an_query(
    query: typing.Any
) -> None:
    """
    execute a query
    """
    if query is None:
        raise ValueError('query must be a sql query')
    await database.execute(query=query)
