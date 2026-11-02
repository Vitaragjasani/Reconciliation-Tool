# Reconciliation Tool

A Snowflake + Streamlit tool for reconciling table/view metadata (row counts,
column lists, primary keys, and numeric sums) against results produced by an
external system.

## How it works

1. A Snowflake stored procedure, [`sql/recon_multi_objects_procedure.sql`](sql/recon_multi_objects_procedure.sql),
   profiles one or more tables/views in a given database/schema and writes the
   results (row counts, columns, primary key flags, numeric sums) into a temp
   table `TMP_RECON_RESULT`.
2. The Streamlit app, [`app.py`](app.py), runs inside Snowflake (via
   Snowpark's active session) or against a Snowflake connection, calls that
   procedure for the objects you select, and compares the results against an
   uploaded CSV/Excel file containing the same metrics from an external
   system.
3. Differences are highlighted with a match/mismatch heatmap, an object-level
   summary table, and a downloadable detailed CSV.

## Setup

1. Run [`sql/recon_multi_objects_procedure.sql`](sql/recon_multi_objects_procedure.sql)
   in your Snowflake account to create the `RECON_MULTI_OBJECTS_WITH_COLUMNS`
   procedure. Replace the `excluded_columns` list in the procedure with your
   own audit/technical columns to exclude (e.g. load timestamps, CDC flags).
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the app (as a Streamlit-in-Snowflake app, or locally with a configured
   Snowflake connection):

   ```bash
   streamlit run app.py
   ```

## Expected external file format

The uploaded CSV/Excel file must contain these columns (case-insensitive):

| Column         | Description                                      |
|----------------|---------------------------------------------------|
| OBJECT_TYPE    | e.g. `BASE TABLE` or `VIEW`                        |
| OBJECT_NAME    | Table/view name                                    |
| METRIC         | `COUNT`, `SUM`, `COLUMN`, or `PRIMARY_KEY`          |
| COLUMN_NAME    | Column name (blank for `COUNT`)                    |
| METRIC_VALUE   | Numeric value for `COUNT`/`SUM` metrics            |

## Usage

1. In the sidebar, enter the Snowflake database and schema to reconcile, and
   the numeric tolerance for comparing sums/counts.
2. Upload the external system's result file.
3. Choose to run reconciliation for all objects found in the file, or select
   specific ones.
4. Click **Run Reconciliation** to compare Snowflake's metadata against the
   uploaded file, and review the heatmap, summary table, and detailed results.
