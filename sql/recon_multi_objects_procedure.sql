-- ============================================================
-- RECON_MULTI_OBJECTS_WITH_COLUMNS
--
-- Snowflake stored procedure that profiles one or more tables/views
-- in a given database/schema and writes row counts, column lists,
-- primary key flags, and numeric column sums into TMP_RECON_RESULT
-- for later comparison against an external system's results.
-- ============================================================

CREATE OR REPLACE PROCEDURE RECON_MULTI_OBJECTS_WITH_COLUMNS(
    DB_NAME STRING,
    SCHEMA_NAME STRING,
    OBJECT_LIST ARRAY
)
RETURNS STRING
LANGUAGE JAVASCRIPT
EXECUTE AS CALLER
AS
$$

//------------------------------------------------------------------
// CREATE TEMP TABLE
//------------------------------------------------------------------
var create_temp = `
CREATE OR REPLACE TEMP TABLE TMP_RECON_RESULT (
    OBJECT_TYPE STRING,
    OBJECT_NAME STRING,
    METRIC STRING,
    COLUMN_NAME STRING,
    METRIC_VALUE NUMBER(38,10)
)
`;

snowflake.execute({ sqlText: create_temp });

//------------------------------------------------------------------
// EXCLUDED COLUMNS
// Audit/technical columns (e.g. CDC or load metadata) that should
// not be included in numeric or column-level reconciliation.
// Update this list to match your own source system's conventions.
//------------------------------------------------------------------
var excluded_columns = [
    'CREATED_TIMESTAMP',
    'LAST_UPDATED_TIMESTAMP',
    'DELETE_FLAG',
    'CHANGE_TIMESTAMP',
    'CDC_FLAG',
    'MERGE_TIMESTAMP'
];

//------------------------------------------------------------------
// LOOP THROUGH OBJECTS
//------------------------------------------------------------------
for (var i = 0; i < OBJECT_LIST.length; i++) {

    var object_name = OBJECT_LIST[i];

    var full_object =
        '"' + DB_NAME + '"."' +
        SCHEMA_NAME + '"."' +
        object_name + '"';

    //------------------------------------------------------------------
    // GET OBJECT TYPE
    //------------------------------------------------------------------
    var type_sql = `
        SELECT TABLE_TYPE
        FROM "${DB_NAME}".INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = '${SCHEMA_NAME}'
          AND TABLE_NAME = '${object_name}'
    `;

    var type_stmt = snowflake.createStatement({
        sqlText: type_sql
    });

    var type_rs = type_stmt.execute();

    var object_type = 'UNKNOWN';

    if (type_rs.next()) {
        object_type = type_rs.getColumnValue(1);
    }

    //------------------------------------------------------------------
    // ROW COUNT
    //------------------------------------------------------------------
    var count_sql = `
        INSERT INTO TMP_RECON_RESULT
        SELECT
            '${object_type}',
            '${object_name}',
            'COUNT',
            NULL,
            COUNT(*)
        FROM ${full_object}
    `;

    snowflake.execute({ sqlText: count_sql });

    //------------------------------------------------------------------
    // FETCH PRIMARY KEY COLUMNS (ONLY FOR TABLES)
    //------------------------------------------------------------------
    var pk_columns = [];

    if (object_type === 'BASE TABLE') {

        try {

            var pk_sql = `
                SHOW PRIMARY KEYS IN TABLE ${full_object}
            `;

            var pk_stmt = snowflake.createStatement({
                sqlText: pk_sql
            });

            var pk_rs = pk_stmt.execute();

            while (pk_rs.next()) {

                //------------------------------------------------------------------
                // COLUMN 5 = COLUMN_NAME
                //------------------------------------------------------------------
                var pk_col = pk_rs.getColumnValue(5);

                pk_columns.push(pk_col.toUpperCase());
            }

        } catch (err) {

            // Ignore PK metadata errors
        }
    }

    //------------------------------------------------------------------
    // FETCH COLUMNS
    //------------------------------------------------------------------
    var col_sql = `
        SELECT COLUMN_NAME, DATA_TYPE
        FROM "${DB_NAME}".INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '${SCHEMA_NAME}'
          AND TABLE_NAME = '${object_name}'
        ORDER BY ORDINAL_POSITION
    `;

    var col_stmt = snowflake.createStatement({
        sqlText: col_sql
    });

    var col_rs = col_stmt.execute();

    //------------------------------------------------------------------
    // PROCESS COLUMNS
    //------------------------------------------------------------------
    while (col_rs.next()) {

        var col_name = col_rs.getColumnValue(1);
        var data_type = col_rs.getColumnValue(2);

        //------------------------------------------------------------------
        // SKIP EXCLUDED COLUMNS
        //------------------------------------------------------------------
        if (excluded_columns.indexOf(col_name.toUpperCase()) >= 0) {
            continue;
        }

        //------------------------------------------------------------------
        // COLUMN METADATA
        //------------------------------------------------------------------
        snowflake.execute({
            sqlText: `
                INSERT INTO TMP_RECON_RESULT
                VALUES (
                    '${object_type}',
                    '${object_name}',
                    'COLUMN',
                    '${col_name}',
                    NULL
                )
            `
        });

        //------------------------------------------------------------------
        // PRIMARY KEY FLAG
        //------------------------------------------------------------------
        var is_pk =
            (object_type === 'BASE TABLE') &&
            (pk_columns.indexOf(col_name.toUpperCase()) >= 0);

        if (is_pk) {

            snowflake.execute({
                sqlText: `
                    INSERT INTO TMP_RECON_RESULT
                    VALUES (
                        '${object_type}',
                        '${object_name}',
                        'PRIMARY_KEY',
                        '${col_name}',
                        NULL
                    )
                `
            });
        }

        //------------------------------------------------------------------
        // NUMERIC COLUMN CHECK
        //------------------------------------------------------------------
        var dtype = data_type.toUpperCase();

        var is_numeric =
               dtype.includes('NUMBER')
            || dtype.includes('DECIMAL')
            || dtype.includes('NUMERIC')
            || dtype.includes('INT')
            || dtype.includes('FLOAT')
            || dtype.includes('DOUBLE')
            || dtype.includes('REAL');

        //------------------------------------------------------------------
        // NUMERIC SUM
        //------------------------------------------------------------------
        if (is_numeric) {

            try {

                snowflake.execute({
                    sqlText: `
                        INSERT INTO TMP_RECON_RESULT
                        SELECT
                            '${object_type}',
                            '${object_name}',
                            'SUM',
                            '${col_name}',
                            COALESCE(SUM("${col_name}"),0)
                        FROM ${full_object}
                    `
                });

            } catch (err) {

                snowflake.execute({
                    sqlText: `
                        INSERT INTO TMP_RECON_RESULT
                        VALUES (
                            '${object_type}',
                            '${object_name}',
                            'ERROR',
                            '${col_name}',
                            NULL
                        )
                    `
                });
            }
        }
    }
}

return 'RECON_COMPLETED';

$$;

-- ============================================================
-- EXAMPLE USAGE
-- Replace the database, schema, and object names below with your own.
-- ============================================================

CALL RECON_MULTI_OBJECTS_WITH_COLUMNS(
    'YOUR_DATABASE',
    'YOUR_SCHEMA',
    ARRAY_CONSTRUCT('TABLE_1', 'TABLE_2')
);

SELECT *
FROM TMP_RECON_RESULT
ORDER BY OBJECT_NAME, METRIC, COLUMN_NAME;
