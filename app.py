import streamlit as st
import pandas as pd
import numpy as np
import re

from snowflake.snowpark.context import get_active_session

# ----------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------
st.set_page_config(
    page_title="Reconciliation Tool",
    layout="wide"
)

st.title("🔍 Data Reconciliation Tool")

# ----------------------------------------------------------
# SIDEBAR
# ----------------------------------------------------------
st.sidebar.header("⚙️ Configuration")

db_name = st.sidebar.text_input(
    "Database",
    value="YOUR_DATABASE"
)

schema_name = st.sidebar.text_input(
    "Schema",
    value="YOUR_SCHEMA"
)

tolerance = st.sidebar.number_input(
    "Numeric Tolerance",
    min_value=0.0,
    value=0.01,
    step=0.01
)

run_button = st.sidebar.button("🚀 Run Reconciliation")

# ----------------------------------------------------------
# FILE UPLOAD
# ----------------------------------------------------------
uploaded_file = st.file_uploader(
    "📂 Upload External System Result (CSV or Excel)",
    type=["csv", "xlsx"]
)

# ----------------------------------------------------------
# VALIDATION
# ----------------------------------------------------------
def validate_columns(df):

    required_cols = {
        "OBJECT_TYPE",
        "OBJECT_NAME",
        "METRIC",
        "COLUMN_NAME",
        "METRIC_VALUE"
    }

    return required_cols.issubset(
        set(df.columns.str.upper())
    )

# ----------------------------------------------------------
# NORMALIZATION
# ----------------------------------------------------------
def normalize_df(df):

    df.columns = df.columns.str.upper()

    text_cols = [
        "OBJECT_TYPE",
        "OBJECT_NAME",
        "METRIC",
        "COLUMN_NAME"
    ]

    for col in text_cols:

        if col in df.columns:

            df[col] = (
                df[col]
                .fillna("")
                .astype(str)
                .str.upper()
                .str.strip()
            )

    return df

# ----------------------------------------------------------
# HEATMAP RENDERER
# ----------------------------------------------------------
def render_binary_heatmap(heatmap_df):

    metric_columns = list(heatmap_df.columns)

    html = """
    <style>
    .recon-heatmap-wrapper {
        overflow-x: auto;
        margin-top: 0.5rem;
        margin-bottom: 1rem;
    }
    .recon-heatmap {
        border-collapse: collapse;
        font-family: sans-serif;
        font-size: 14px;
        min-width: 700px;
    }
    .recon-heatmap th,
    .recon-heatmap td {
        border: 1px solid #d1d5db;
        padding: 8px 12px;
        text-align: center;
    }
    .recon-heatmap th {
        background-color: #f3f4f6;
        font-weight: 600;
    }
    .recon-heatmap .object-cell {
        text-align: left;
        white-space: nowrap;
        background-color: #ffffff;
        font-weight: 600;
    }
    .recon-green {
        background-color: #16a34a;
    }
    .recon-red {
        background-color: #dc2626;
    }
    .recon-blank {
        background-color: #ffffff;
    }
    </style>
    <div class="recon-heatmap-wrapper">
      <table class="recon-heatmap">
        <thead>
          <tr>
            <th>OBJECT_NAME</th>
    """

    for metric in metric_columns:
        html += f"<th>{metric}</th>"

    html += """
          </tr>
        </thead>
        <tbody>
    """

    for object_name, row in heatmap_df.iterrows():
        html += f'<tr><td class="object-cell">{object_name}</td>'

        for metric in metric_columns:
            value = row[metric]

            if pd.isna(value):
                cell_class = "recon-blank"
            elif value == 1:
                cell_class = "recon-green"
            else:
                cell_class = "recon-red"

            html += f'<td class="{cell_class}"></td>'

        html += "</tr>"

    html += """
        </tbody>
      </table>
    </div>
    """

    st.markdown(html, unsafe_allow_html=True)

# ----------------------------------------------------------
# MAIN
# ----------------------------------------------------------
if uploaded_file is not None:

    try:

        # ----------------------------------------------------------
        # READ FILE
        # ----------------------------------------------------------
        if uploaded_file.name.endswith(".csv"):
            df_external = pd.read_csv(uploaded_file)
        else:
            df_external = pd.read_excel(uploaded_file)

        if df_external.empty:
            st.error("❌ Uploaded file is empty.")
            st.stop()

        if not validate_columns(df_external):
            st.error("❌ Invalid file format.")
            st.stop()

        df_external = normalize_df(df_external)

        st.success("✅ File uploaded and validated")

        # ----------------------------------------------------------
        # OBJECT LIST
        # ----------------------------------------------------------
        object_list = (
            df_external["OBJECT_NAME"]
            .dropna()
            .unique()
            .tolist()
        )

        object_list = [
            obj for obj in object_list
            if re.match(r'^[A-Z0-9_]+$', obj)
        ]

        if not object_list:
            st.error("❌ No valid object names found.")
            st.stop()

        # ----------------------------------------------------------
        # OBJECT SELECTION
        # ----------------------------------------------------------
        st.subheader("🎯 Select Reconciliation Scope")

        option = st.radio(
            "Choose option:",
            [
                "Run for ALL objects",
                "Select specific objects"
            ]
        )

        if option == "Run for ALL objects":

            selected_objects = object_list

        else:

            selected_objects = st.multiselect(
                "Select objects:",
                object_list,
                default=object_list[:1]
            )

        st.info(f"📌 Selected {len(selected_objects)} object(s)")

        # ----------------------------------------------------------
        # RUN RECON (store results in session state)
        # ----------------------------------------------------------
        if run_button:

            if not selected_objects:
                st.error("❌ Please select at least one object.")
                st.stop()

            object_list_sql = ",".join(
                [f"'{obj}'" for obj in selected_objects]
            )

            session = get_active_session()

            with st.spinner("⚡ Running reconciliation..."):

                session.sql(f"""
                    CALL RECON_MULTI_OBJECTS_WITH_COLUMNS(
                        '{db_name}',
                        '{schema_name}',
                        ARRAY_CONSTRUCT({object_list_sql})
                    )
                """).collect()

                df_snowflake = session.sql("""
                    SELECT *
                    FROM TMP_RECON_RESULT
                """).to_pandas()

            if df_snowflake.empty:
                st.error("❌ No data returned.")
                st.stop()

            # ----------------------------------------------------------
            # NORMALIZE
            # ----------------------------------------------------------
            df_snowflake = normalize_df(df_snowflake)

            df_external_filtered = df_external[
                df_external["OBJECT_NAME"].isin(
                    selected_objects
                )
            ].copy()

            # ----------------------------------------------------------
            # DEDUPLICATE EXTERNAL FILE
            # ----------------------------------------------------------
            df_external_filtered = df_external_filtered.drop_duplicates(
                subset=[
                    "OBJECT_TYPE",
                    "OBJECT_NAME",
                    "METRIC",
                    "COLUMN_NAME"
                ]
            )

            # ----------------------------------------------------------
            # NULL SAFE FOR MERGE
            # ----------------------------------------------------------
            for col in ["COLUMN_NAME"]:

                df_snowflake[col] = (
                    df_snowflake[col]
                    .fillna("")
                )

                df_external_filtered[col] = (
                    df_external_filtered[col]
                    .fillna("")
                )

            # ----------------------------------------------------------
            # MERGE
            # ----------------------------------------------------------
            df_compare = pd.merge(
                df_snowflake,
                df_external_filtered,
                on=[
                    "OBJECT_TYPE",
                    "OBJECT_NAME",
                    "METRIC",
                    "COLUMN_NAME"
                ],
                how="outer",
                suffixes=("_SNOW", "_EXT"),
                indicator=True
            )

            # ----------------------------------------------------------
            # NUMERIC CONVERSION
            # ----------------------------------------------------------
            df_compare["METRIC_VALUE_SNOW"] = pd.to_numeric(
                df_compare["METRIC_VALUE_SNOW"],
                errors="coerce"
            )

            df_compare["METRIC_VALUE_EXT"] = pd.to_numeric(
                df_compare["METRIC_VALUE_EXT"],
                errors="coerce"
            )

            # ----------------------------------------------------------
            # DEFAULT COLUMNS
            # ----------------------------------------------------------
            df_compare["DIFF"] = np.nan
            df_compare["PCT_DIFF"] = np.nan
            df_compare["MATCH"] = "✘"
            df_compare["MATCH_REASON"] = ""

            # ----------------------------------------------------------
            # METRIC GROUPS
            # ----------------------------------------------------------
            metric_mask = df_compare["METRIC"].isin([
                "COUNT",
                "SUM"
            ])

            column_mask = (
                df_compare["METRIC"] == "COLUMN"
            )

            pk_mask = (
                df_compare["METRIC"] == "PRIMARY_KEY"
            )

            error_mask = (
                df_compare["METRIC"] == "ERROR"
            )

            # ----------------------------------------------------------
            # DIFF
            # ----------------------------------------------------------
            df_compare["DIFF"] = np.where(
                metric_mask,
                df_compare["METRIC_VALUE_SNOW"]
                - df_compare["METRIC_VALUE_EXT"],
                np.nan
            )

            # ----------------------------------------------------------
            # PERCENT DIFF
            # ----------------------------------------------------------
            df_compare["PCT_DIFF"] = np.where(
                (
                    metric_mask
                    & df_compare["METRIC_VALUE_EXT"].notna()
                    & (df_compare["METRIC_VALUE_EXT"] != 0)
                ),
                (
                    df_compare["DIFF"]
                    / df_compare["METRIC_VALUE_EXT"]
                ) * 100,
                np.nan
            )

            # ----------------------------------------------------------
            # NUMERIC MATCH
            # ----------------------------------------------------------
            df_compare.loc[metric_mask, "MATCH"] = np.where(
                (
                    df_compare.loc[metric_mask, "DIFF"]
                    .abs() <= tolerance
                ),
                "✔",
                "✘"
            )

            # ----------------------------------------------------------
            # COLUMN MATCH
            # ----------------------------------------------------------
            df_compare.loc[column_mask, "MATCH"] = np.where(
                df_compare.loc[column_mask, "_merge"] == "both",
                "✔",
                "✘"
            )

            # ----------------------------------------------------------
            # PRIMARY KEY MATCH
            # ----------------------------------------------------------
            df_compare.loc[pk_mask, "MATCH"] = np.where(
                df_compare.loc[pk_mask, "_merge"] == "both",
                "✔",
                "✘"
            )

            # ----------------------------------------------------------
            # ERROR METRICS
            # ----------------------------------------------------------
            df_compare.loc[error_mask, "MATCH"] = "✘"

            # ----------------------------------------------------------
            # MATCH REASON
            # ----------------------------------------------------------
            df_compare.loc[
                df_compare["_merge"] == "left_only",
                "MATCH_REASON"
            ] = "Exists only in Snowflake"

            df_compare.loc[
                df_compare["_merge"] == "right_only",
                "MATCH_REASON"
            ] = "Exists only in External"

            df_compare.loc[
                (
                    metric_mask
                    & (
                        df_compare["DIFF"]
                        .abs() <= tolerance
                    )
                ),
                "MATCH_REASON"
            ] = "Numeric Match"

            df_compare.loc[
                (
                    metric_mask
                    & (
                        df_compare["DIFF"]
                        .abs() > tolerance
                    )
                ),
                "MATCH_REASON"
            ] = "Numeric Difference"

            df_compare.loc[
                (
                    column_mask
                    & (df_compare["_merge"] == "both")
                ),
                "MATCH_REASON"
            ] = "Column Match"

            df_compare.loc[
                (
                    pk_mask
                    & (df_compare["_merge"] == "both")
                ),
                "MATCH_REASON"
            ] = "Primary Key Match"

            df_compare.loc[
                error_mask,
                "MATCH_REASON"
            ] = "Aggregation Error"

            # ----------------------------------------------------------
            # CLEAN MERGE LABEL
            # ----------------------------------------------------------
            df_compare["_merge"] = df_compare["_merge"].replace({
                "left_only": "Snowflake Only",
                "right_only": "External Only",
                "both": "Both"
            })

            # ----------------------------------------------------------
            # STORE IN SESSION STATE
            # ----------------------------------------------------------
            st.session_state["df_compare"] = df_compare
            st.session_state["selected_objects"] = selected_objects

        # ----------------------------------------------------------
        # DISPLAY RESULTS FROM SESSION STATE
        # ----------------------------------------------------------
        if "df_compare" in st.session_state:

            df_compare = st.session_state["df_compare"]
            selected_objects = st.session_state["selected_objects"]

            # ----------------------------------------------------------
            # SUMMARY
            # ----------------------------------------------------------
            st.subheader("📊 Summary")

            total = len(df_compare)

            matches = len(
                df_compare[
                    df_compare["MATCH"] == "✔"
                ]
            )

            mismatches = len(
                df_compare[
                    df_compare["MATCH"] == "✘"
                ]
            )

            pk_checks = len(
                df_compare[
                    df_compare["METRIC"] == "PRIMARY_KEY"
                ]
            )

            match_rate = (
                round((matches / total) * 100, 2)
                if total > 0 else 0
            )

            col1, col2, col3, col4, col5 = st.columns(5)

            col1.metric("Total Checks", total)
            col2.metric("Matches", matches)
            col3.metric("Mismatches", mismatches)
            col4.metric("PK Checks", pk_checks)
            col5.metric("Match Rate %", f"{match_rate}%")

            # ----------------------------------------------------------
            # BINARY HEATMAP WITH LEGEND
            # ----------------------------------------------------------
            heatmap_header_col, heatmap_legend_col = st.columns([3, 1])

            with heatmap_header_col:
                st.subheader("🟩🟥 Reconciliation Heatmap")

            with heatmap_legend_col:
                legend_html = """
                <div style="display: flex; align-items: center; gap: 12px; padding-top: 1.2rem; font-size: 13px; font-family: sans-serif;">
                    <span style="display: inline-flex; align-items: center; gap: 4px;">
                        <span style="width: 14px; height: 14px; background-color: #16a34a; display: inline-block; border-radius: 2px;"></span> Match
                    </span>
                    <span style="display: inline-flex; align-items: center; gap: 4px;">
                        <span style="width: 14px; height: 14px; background-color: #dc2626; display: inline-block; border-radius: 2px;"></span> Mismatch
                    </span>
                    <span style="display: inline-flex; align-items: center; gap: 4px;">
                        <span style="width: 14px; height: 14px; background-color: #ffffff; border: 1px solid #d1d5db; display: inline-block; border-radius: 2px;"></span> No Reconciliation
                    </span>
                </div>
                """
                st.markdown(legend_html, unsafe_allow_html=True)

            heatmap_metrics = [
                "COUNT",
                "SUM",
                "COLUMN",
                "PRIMARY_KEY"
            ]

            heatmap_source = df_compare[
                df_compare["METRIC"].isin(heatmap_metrics)
            ].copy()

            heatmap_summary = (
                heatmap_source
                .groupby(["OBJECT_NAME", "METRIC"])["MATCH"]
                .apply(
                    lambda values: (
                        0 if (values == "✘").any()
                        else 1 if (values == "✔").any()
                        else np.nan
                    )
                )
                .reset_index(name="MATCH_FLAG")
            )

            heatmap_df = heatmap_summary.pivot(
                index="OBJECT_NAME",
                columns="METRIC",
                values="MATCH_FLAG"
            )

            heatmap_objects = sorted(selected_objects)
            heatmap_df = heatmap_df.reindex(index=heatmap_objects)
            heatmap_df = heatmap_df.reindex(columns=heatmap_metrics)

            render_binary_heatmap(heatmap_df)

            # ----------------------------------------------------------
            # OBJECT-LEVEL SUMMARY TABLE
            # ----------------------------------------------------------
            st.subheader("📋 Object-Level Summary")

            summary_source = df_compare[
                ~(
                    (df_compare["OBJECT_TYPE"] == "VIEW")
                    & (df_compare["METRIC"] == "PRIMARY_KEY")
                )
            ].copy()

            summary_table_df = (
                summary_source
                .groupby(["OBJECT_NAME", "METRIC"])["MATCH"]
                .agg(
                    NO_OF_CHECKS_MATCHED=lambda x: (x == "✔").sum(),
                    NO_OF_CHECKS_FAILED=lambda x: (x == "✘").sum()
                )
                .reset_index()
                .rename(columns={"METRIC": "CATEGORY"})
                .sort_values(by=["OBJECT_NAME", "CATEGORY"])
                .reset_index(drop=True)
            )

            st.dataframe(
                summary_table_df,
                use_container_width=True
            )

            summary_csv = summary_table_df.to_csv(index=False)

            st.download_button(
                "📥 Download Summary",
                data=summary_csv,
                file_name="object_level_summary.csv",
                mime="text/csv"
            )

            # ----------------------------------------------------------
            # FILTERS
            # ----------------------------------------------------------
            st.subheader("🔎 Filters")

            metric_filter = st.multiselect(
                "Filter Metrics",
                sorted(
                    df_compare["METRIC"]
                    .dropna()
                    .unique()
                ),
                default=sorted(
                    df_compare["METRIC"]
                    .dropna()
                    .unique()
                )
            )

            object_filter = st.multiselect(
                "Filter Objects",
                sorted(
                    df_compare["OBJECT_NAME"]
                    .dropna()
                    .unique()
                ),
                default=sorted(
                    df_compare["OBJECT_NAME"]
                    .dropna()
                    .unique()
                )
            )

            show_only_mismatch = st.checkbox(
                "Show only mismatches"
            )

            # ----------------------------------------------------------
            # DISPLAY FILTER
            # ----------------------------------------------------------
            display_df = df_compare[
                (
                    df_compare["METRIC"]
                    .isin(metric_filter)
                )
                &
                (
                    df_compare["OBJECT_NAME"]
                    .isin(object_filter)
                )
            ]

            if show_only_mismatch:
                display_df = display_df[
                    display_df["MATCH"] == "✘"
                ]

            display_df = display_df.sort_values(
                by=[
                    "OBJECT_NAME",
                    "METRIC",
                    "COLUMN_NAME"
                ]
            )

            # ----------------------------------------------------------
            # DISPLAY
            # ----------------------------------------------------------
            st.subheader("📋 Results")

            st.dataframe(
                display_df,
                use_container_width=True,
                height=700
            )

            # ----------------------------------------------------------
            # DOWNLOAD
            # ----------------------------------------------------------
            csv = df_compare.to_csv(index=False)

            st.download_button(
                "📥 Download Results",
                data=csv,
                file_name="reconciliation_result.csv",
                mime="text/csv"
            )

            st.success("✅ Reconciliation completed!")

    except Exception as e:

        st.error(f"❌ Error: {str(e)}")
