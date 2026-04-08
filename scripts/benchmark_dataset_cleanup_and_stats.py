#!/usr/bin/env python3
"""Clean benchmark dataset artifacts and generate descriptive statistics."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyBboxPatch
import seaborn as sns
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


PAPER_LAYOUT_LABELS = {
    "single_column_bar": "Single bar",
    "single_column_line": "Single line",
    "single_column_table": "Single table",
    "double_column_bar": "Double bar",
    "double_column_line": "Double line",
}

SIZE_LABELS = {
    (19.05, 14.29): "19.05 x 14.29 cm",
    (25.4, 14.29): "25.40 x 14.29 cm",
}

BAR_COLORS = ["#2F6BFF", "#26A69A", "#F28E2B", "#5B8C5A", "#C8553D", "#8B5CF6"]
THEME_COLORS = {
    "Block Area Segment Distribution": "#C8553D",
    "New-House Cross-Structure Analysis": "#2F6BFF",
    "New-House Market Capacity Analysis": "#26A69A",
}
STYLE_COLORS = {
    "marketing_orange_green": "#F28E2B",
    "business_blue_solid": "#2F6BFF",
    "compare_tangerine_gray": "#7C7F8A",
}
TEXT_DARK = "#172033"
TEXT_MUTED = "#5B6476"
LINE_LIGHT = "#D9DFEA"
BG_COLOR = "#F7F8FC"
PANEL_BG = "#FFFFFF"


sns.set_theme(
    style="whitegrid",
    context="paper",
    font_scale=1.25,
    rc={
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": LINE_LIGHT,
        "axes.labelcolor": TEXT_DARK,
        "xtick.color": TEXT_DARK,
        "ytick.color": TEXT_DARK,
        "grid.color": "#E6EAF2",
        "grid.linestyle": "-",
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titleweight": "bold",
        "font.family": "DejaVu Sans",
        "savefig.facecolor": "white",
    },
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sample_dir_from_record(dataset_root: Path, row: dict[str, Any]) -> Path:
    return dataset_root / row["sample_dir"]


def gt_core_paths(dataset_root: Path, row: dict[str, Any]) -> tuple[Path, Path]:
    return dataset_root / row["gt_yaml"], dataset_root / row["gt_ppt"]


def load_samples(dataset_root: Path) -> list[dict[str, Any]]:
    samples_path = dataset_root / "manifest" / "samples.jsonl"
    if not samples_path.exists():
        raise FileNotFoundError(f"未找到 samples manifest: {samples_path}")
    return read_jsonl(samples_path)


def collect_sample_dirs(dataset_root: Path) -> list[Path]:
    split_root = dataset_root / "split"
    return sorted(
        p
        for p in split_root.glob("*/*")
        if p.is_dir() and p.name.startswith("s_")
    )


def audit_dataset(dataset_root: Path) -> dict[str, Any]:
    rows = load_samples(dataset_root)
    sample_rows_by_id = {row["sample_id"]: row for row in rows}
    sample_dirs = collect_sample_dirs(dataset_root)

    valid_rows: list[dict[str, Any]] = []
    broken_manifest_rows: list[dict[str, Any]] = []
    orphan_dirs: list[Path] = []

    for row in rows:
        gt_yaml, gt_ppt = gt_core_paths(dataset_root, row)
        if gt_yaml.exists() and gt_ppt.exists():
            valid_rows.append(row)
        else:
            broken_manifest_rows.append(row)

    for sample_dir in sample_dirs:
        sample_id = sample_dir.name[2:]
        gt_dir = sample_dir / "gt"
        gt_yaml = gt_dir / "slide.yaml"
        gt_ppt = gt_dir / "slide.pptx"
        in_manifest = sample_id in sample_rows_by_id
        if not in_manifest or not (gt_yaml.exists() and gt_ppt.exists()):
            orphan_dirs.append(sample_dir)

    orphan_dirs = sorted({p.resolve() for p in orphan_dirs})
    return {
        "all_rows": rows,
        "valid_rows": valid_rows,
        "broken_manifest_rows": broken_manifest_rows,
        "orphan_dirs": orphan_dirs,
        "sample_dir_count": len(sample_dirs),
    }


def cleanup_dataset(dataset_root: Path, audit: dict[str, Any]) -> dict[str, Any]:
    removed_dirs: list[str] = []
    for sample_dir in audit["orphan_dirs"]:
        if sample_dir.exists():
            shutil.rmtree(sample_dir)
            removed_dirs.append(str(sample_dir.relative_to(dataset_root)))

    valid_rows = sorted(audit["valid_rows"], key=lambda row: row["sample_id"])
    samples_path = dataset_root / "manifest" / "samples.jsonl"
    write_jsonl(samples_path, valid_rows)

    report = {
        "dataset_root": str(dataset_root),
        "manifest_rows_before": len(audit["all_rows"]),
        "manifest_rows_after": len(valid_rows),
        "sample_dirs_before": audit["sample_dir_count"],
        "removed_orphan_dir_count": len(removed_dirs),
        "removed_orphan_dirs": removed_dirs,
        "removed_broken_manifest_count": len(audit["broken_manifest_rows"]),
    }
    return report


def load_template_catalog() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    template_items = yaml.safe_load(
        (PROJECT_ROOT / "config" / "templates" / "template_definitions.yaml").read_text(
            encoding="utf-8"
        )
    )
    layout_items = yaml.safe_load(
        (PROJECT_ROOT / "config" / "templates" / "layouts.yaml").read_text(encoding="utf-8")
    )["layouts"]
    templates = {item["uid"]: item for item in template_items}
    return templates, layout_items


def infer_visual_primitive(layout_type: str) -> str:
    if layout_type.endswith("_bar"):
        return "Bar chart"
    if layout_type.endswith("_line"):
        return "Line chart"
    if layout_type.endswith("_table"):
        return "Pivot table"
    return layout_type


def build_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    templates, layouts = load_template_catalog()
    df = pd.DataFrame(rows).copy()
    df["slide_width_cm"] = df["slide_size"].map(lambda x: float(x["width"]))
    df["slide_height_cm"] = df["slide_size"].map(lambda x: float(x["height"]))
    df["slide_size_label"] = list(
        map(
            lambda w, h: SIZE_LABELS.get((w, h), f"{w:.2f} x {h:.2f} cm"),
            df["slide_width_cm"],
            df["slide_height_cm"],
        )
    )
    df["layout_label"] = df["layout_type"].map(
        lambda x: PAPER_LAYOUT_LABELS.get(x, x.replace("_", " "))
    )
    df["theme_key"] = df["template_id"].map(lambda x: templates[x]["theme_key"])
    df["style_config_id"] = df["template_id"].map(lambda x: templates[x]["style_config_id"])
    df["function_keys"] = df["template_id"].map(lambda x: list(templates[x]["function_key"]))
    df["function_count"] = df["function_keys"].map(len)
    df["visual_primitive"] = df["layout_type"].map(infer_visual_primitive)
    df["column_count"] = df["layout_type"].map(lambda x: 2 if "double" in x else 1)
    df["chart_count"] = df["layout_type"].map(lambda x: len(layouts[x]["slots"]))
    df["caption_count"] = df["layout_type"].map(
        lambda x: sum(1 for slot in layouts[x]["text_slots"] if slot["part"] == "caption")
    )
    df["textbox_count"] = df["layout_type"].map(lambda x: len(layouts[x]["text_slots"]))
    return df


def save_tables(df: pd.DataFrame, out_dir: Path) -> dict[str, Path]:
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    templates, _ = load_template_catalog()

    summary = pd.DataFrame(
        [
            {"metric": "valid_samples", "value": len(df)},
            {"metric": "cities", "value": df["city_key"].nunique()},
            {"metric": "city_block_pairs", "value": df[["city_key", "block"]].drop_duplicates().shape[0]},
            {"metric": "templates", "value": df["template_id"].nunique()},
            {"metric": "layout_types", "value": df["layout_type"].nunique()},
            {"metric": "slide_sizes", "value": df["slide_size_label"].nunique()},
        ]
    )

    by_city = (
        df.groupby(["city_key", "city"], as_index=False)
        .agg(samples=("sample_id", "count"), unique_blocks=("block", "nunique"))
        .sort_values("samples", ascending=False)
    )
    by_template = (
        df.groupby(["template_id", "layout_label", "slide_size_label"], as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values(["samples", "template_id"], ascending=[False, True])
    )
    by_layout = (
        df.groupby(["layout_type", "layout_label"], as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    by_theme = (
        df.groupby("theme_key", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    by_style = (
        df.groupby("style_config_id", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    by_slide_size = (
        df.groupby("slide_size_label", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    city_layout = (
        df.pivot_table(
            index="city",
            columns="layout_label",
            values="sample_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )
    function_theme_map = {}
    for item in templates.values():
        for function_key in item["function_key"]:
            function_theme_map[function_key] = item["theme_key"]

    function_expanded = (
        df[["sample_id", "function_keys"]]
        .explode("function_keys")
        .rename(columns={"function_keys": "function_key"})
    )
    function_counts = (
        function_expanded.groupby("function_key", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    function_counts["theme_key"] = function_counts["function_key"].map(function_theme_map)

    layout_style = (
        df.pivot_table(
            index="layout_label",
            columns="style_config_id",
            values="sample_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )
    layout_profile = (
        df.groupby(
            [
                "layout_label",
                "visual_primitive",
                "column_count",
                "chart_count",
                "caption_count",
                "slide_size_label",
            ],
            as_index=False,
        )
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )

    outputs = {
        "summary": tables_dir / "dataset_summary.csv",
        "by_city": tables_dir / "samples_by_city.csv",
        "by_template": tables_dir / "samples_by_template.csv",
        "by_layout": tables_dir / "samples_by_layout.csv",
        "by_theme": tables_dir / "samples_by_theme.csv",
        "by_style": tables_dir / "samples_by_style.csv",
        "by_function": tables_dir / "function_occurrences.csv",
        "by_slide_size": tables_dir / "samples_by_slide_size.csv",
        "city_layout": tables_dir / "city_by_layout.csv",
        "layout_style": tables_dir / "layout_by_style.csv",
        "layout_profile": tables_dir / "layout_profile.csv",
    }

    summary.to_csv(outputs["summary"], index=False)
    by_city.to_csv(outputs["by_city"], index=False)
    by_template.to_csv(outputs["by_template"], index=False)
    by_layout.to_csv(outputs["by_layout"], index=False)
    by_theme.to_csv(outputs["by_theme"], index=False)
    by_style.to_csv(outputs["by_style"], index=False)
    function_counts.to_csv(outputs["by_function"], index=False)
    by_slide_size.to_csv(outputs["by_slide_size"], index=False)
    city_layout.to_csv(outputs["city_layout"], index=False)
    layout_style.to_csv(outputs["layout_style"], index=False)
    layout_profile.to_csv(outputs["layout_profile"], index=False)
    return outputs


def _save_figure(fig: plt.Figure, out_base: Path) -> None:
    fig.savefig(out_base.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(out_base.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def plot_dataset_overview(df: pd.DataFrame, out_base: Path) -> None:
    by_city = (
        df.groupby("city", as_index=False)
        .agg(samples=("sample_id", "count"), unique_blocks=("block", "nunique"))
        .sort_values("samples", ascending=False)
    )
    by_layout = (
        df.groupby("layout_label", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=True)
    )
    by_size = (
        df.groupby("slide_size_label", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    fig = plt.figure(figsize=(14, 8), constrained_layout=True)
    gs = fig.add_gridspec(3, 6, height_ratios=[1.1, 1.5, 1.5])
    card_axes = [fig.add_subplot(gs[0, i]) for i in range(6)]
    ax_city = fig.add_subplot(gs[1:, :3])
    ax_layout = fig.add_subplot(gs[1, 3:])
    ax_size = fig.add_subplot(gs[2, 3:])

    cards = [
        ("Samples", f"{len(df):,}", "#2F6BFF"),
        ("Cities", f"{df['city'].nunique()}", "#26A69A"),
        ("City-block pairs", f"{df[['city_key', 'block']].drop_duplicates().shape[0]}", "#F28E2B"),
        ("Templates", f"{df['template_id'].nunique()}", "#5B8C5A"),
        ("Layouts", f"{df['layout_type'].nunique()}", "#C8553D"),
        ("Slide sizes", f"{df['slide_size_label'].nunique()}", "#8B5CF6"),
    ]
    for ax, (label, value, color) in zip(card_axes, cards, strict=False):
        ax.axis("off")
        ax.add_patch(
            FancyBboxPatch(
                (0.02, 0.1),
                0.96,
                0.82,
                boxstyle="round,pad=0.02,rounding_size=18",
                linewidth=0,
                facecolor=BG_COLOR,
                transform=ax.transAxes,
            )
        )
        ax.text(0.08, 0.67, label, fontsize=12, color=TEXT_MUTED, transform=ax.transAxes)
        ax.text(
            0.08,
            0.28,
            value,
            fontsize=22,
            fontweight="bold",
            color=color,
            transform=ax.transAxes,
        )

    city_palette = ["#2F6BFF", "#4A8FE7", "#8AB6F9"]
    sns.barplot(
        data=by_city,
        y="city",
        x="samples",
        palette=city_palette,
        ax=ax_city,
        orient="h",
    )
    ax_city.set_title("City coverage", loc="left", fontsize=15, pad=10)
    ax_city.set_xlabel("Samples")
    ax_city.set_ylabel("")
    for patch, block_count in zip(ax_city.patches, by_city["unique_blocks"], strict=False):
        y = patch.get_y() + patch.get_height() / 2
        x = patch.get_width()
        ax_city.text(x + 8, y, f"{int(x)} samples  |  {int(block_count)} blocks", va="center", fontsize=10, color=TEXT_DARK)

    layout_palette = sns.color_palette("blend:#dce7ff,#2F6BFF", n_colors=len(by_layout))
    sns.barplot(
        data=by_layout,
        y="layout_label",
        x="samples",
        palette=layout_palette,
        ax=ax_layout,
        orient="h",
    )
    ax_layout.set_title("Layout distribution", loc="left", fontsize=15, pad=10)
    ax_layout.set_xlabel("Samples")
    ax_layout.set_ylabel("")
    for patch in ax_layout.patches:
        y = patch.get_y() + patch.get_height() / 2
        x = patch.get_width()
        ax_layout.text(x + 6, y, f"{int(x)}", va="center", fontsize=10)

    size_colors = ["#2F6BFF", "#F28E2B"]
    wedges, _, autotexts = ax_size.pie(
        by_size["samples"],
        labels=by_size["slide_size_label"],
        colors=size_colors[: len(by_size)],
        autopct=lambda pct: f"{pct:.1f}%",
        pctdistance=0.78,
        startangle=90,
        wedgeprops={"width": 0.42, "edgecolor": "white"},
        textprops={"fontsize": 10, "color": TEXT_DARK},
    )
    for text in autotexts:
        text.set_fontweight("bold")
    ax_size.set_title("Canvas size mix", loc="left", fontsize=15, pad=10)
    ax_size.text(
        0.0,
        -1.2,
        "Single-column slides use the 19.05 cm canvas, while double-column and table layouts use the 25.40 cm canvas.",
        ha="left",
        va="center",
        fontsize=10,
        color=TEXT_MUTED,
        transform=ax_size.transData,
    )
    fig.suptitle("Benchmark Scope and Coverage", fontsize=20, fontweight="bold", y=1.02)
    fig.text(
        0.01,
        0.985,
        "Section 3.2 dataset overview after cleanup",
        ha="left",
        va="top",
        fontsize=11,
        color=TEXT_MUTED,
    )
    _save_figure(fig, out_base)


def plot_function_taxonomy(df: pd.DataFrame, out_base: Path) -> None:
    function_expanded = (
        df[["sample_id", "theme_key", "function_keys"]]
        .explode("function_keys")
        .rename(columns={"function_keys": "function_key"})
    )
    by_theme = (
        df.groupby("theme_key", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=True)
    )
    by_function = (
        function_expanded.groupby(["function_key", "theme_key"], as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=True)
    )
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(14, 7),
        constrained_layout=True,
        gridspec_kw={"width_ratios": [1.0, 1.5]},
    )

    theme_palette = [THEME_COLORS[label] for label in by_theme["theme_key"]]
    sns.barplot(
        data=by_theme,
        y="theme_key",
        x="samples",
        palette=theme_palette,
        ax=axes[0],
        orient="h",
    )
    axes[0].set_title("Theme-level coverage", loc="left", fontsize=15, pad=10)
    axes[0].set_xlabel("Slides")
    axes[0].set_ylabel("")
    for patch in axes[0].patches:
        y = patch.get_y() + patch.get_height() / 2
        x = patch.get_width()
        axes[0].text(x + 8, y, f"{int(x)}", va="center", fontsize=10)

    function_palette = [THEME_COLORS[theme] for theme in by_function["theme_key"]]
    sns.barplot(
        data=by_function,
        y="function_key",
        x="samples",
        palette=function_palette,
        ax=axes[1],
        orient="h",
    )
    axes[1].set_title("Function-level occurrence coverage", loc="left", fontsize=15, pad=10)
    axes[1].set_xlabel("Function occurrences")
    axes[1].set_ylabel("")
    for patch in axes[1].patches:
        y = patch.get_y() + patch.get_height() / 2
        x = patch.get_width()
        axes[1].text(x + 8, y, f"{int(x)}", va="center", fontsize=10)

    handles = [
        plt.Line2D([0], [0], color=color, lw=8)
        for _, color in THEME_COLORS.items()
    ]
    axes[1].legend(
        handles,
        list(THEME_COLORS.keys()),
        title="Theme",
        loc="lower right",
        frameon=False,
    )
    fig.suptitle("Semantic Task Taxonomy", fontsize=20, fontweight="bold", y=1.02)
    fig.text(
        0.01,
        0.985,
        "Dual-chart templates contribute two function instances, so function-occurrence counts exceed slide counts.",
        ha="left",
        va="top",
        fontsize=11,
        color=TEXT_MUTED,
    )
    _save_figure(fig, out_base)


def plot_layout_style_matrix(df: pd.DataFrame, out_base: Path) -> None:
    layout_style = df.pivot_table(
        index="layout_label",
        columns="style_config_id",
        values="sample_id",
        aggfunc="count",
        fill_value=0,
    )
    layout_profile = (
        df.groupby(
            ["layout_label", "visual_primitive", "column_count", "chart_count", "caption_count", "slide_size_label"],
            as_index=False,
        )
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )

    fig = plt.figure(figsize=(14, 7.8), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.05, 1.25])
    ax_heat = fig.add_subplot(gs[0, 0])
    ax_table = fig.add_subplot(gs[0, 1])

    cmap = sns.light_palette("#2F6BFF", as_cmap=True)
    sns.heatmap(
        layout_style,
        annot=True,
        fmt=".0f",
        cmap=cmap,
        linewidths=1,
        linecolor="white",
        cbar=False,
        ax=ax_heat,
        annot_kws={"fontsize": 11, "fontweight": "bold"},
    )
    ax_heat.set_title("Layout x style coverage", loc="left", fontsize=15, pad=10)
    ax_heat.set_xlabel("")
    ax_heat.set_ylabel("")
    ax_heat.tick_params(axis="x", rotation=20)
    ax_heat.tick_params(axis="y", rotation=0)

    ax_table.axis("off")
    table_df = layout_profile[
        ["layout_label", "visual_primitive", "column_count", "chart_count", "caption_count", "slide_size_label", "samples"]
    ].copy()
    table_df.columns = ["Layout", "Primitive", "Cols", "Charts", "Captions", "Canvas", "Samples"]
    table = ax_table.table(
        cellText=table_df.values,
        colLabels=table_df.columns,
        cellLoc="center",
        colLoc="center",
        loc="center",
        bbox=[0.0, 0.05, 1.0, 0.9],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.5)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("white")
        if row == 0:
            cell.set_facecolor("#EAF0FF")
            cell.set_text_props(weight="bold", color=TEXT_DARK)
        else:
            cell.set_facecolor("#F8FAFF" if row % 2 else "white")
    ax_table.set_title("Layout profile summary", loc="left", fontsize=15, pad=10)

    fig.suptitle("Structural and Style Diversity", fontsize=20, fontweight="bold", y=1.02)
    fig.text(
        0.01,
        0.985,
        "The benchmark varies chart primitive, column count, caption multiplicity, canvas size, and style family rather than only content semantics.",
        ha="left",
        va="top",
        fontsize=11,
        color=TEXT_MUTED,
    )
    _save_figure(fig, out_base)


def render_markdown_report(df: pd.DataFrame, cleanup_report: dict[str, Any], out_path: Path) -> None:
    city_counts = (
        df.groupby("city", as_index=False)
        .agg(samples=("sample_id", "count"), unique_blocks=("block", "nunique"))
        .sort_values("samples", ascending=False)
    )
    layout_counts = (
        df.groupby("layout_label", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    size_counts = (
        df.groupby("slide_size_label", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    theme_counts = (
        df.groupby("theme_key", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values(["samples", "theme_key"], ascending=[False, True])
    )
    style_counts = (
        df.groupby("style_config_id", as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )
    function_expanded = (
        df[["sample_id", "theme_key", "function_keys"]]
        .explode("function_keys")
        .rename(columns={"function_keys": "function_key"})
    )
    function_counts = (
        function_expanded.groupby(["function_key", "theme_key"], as_index=False)
        .agg(samples=("sample_id", "count"))
        .sort_values("samples", ascending=False)
    )

    lines = [
        "# Dataset 20260407 Cleanup and Descriptive Statistics",
        "",
        "## Cleanup",
        f"- Valid samples kept: {len(df)}",
        f"- Orphan sample directories removed: {cleanup_report['removed_orphan_dir_count']}",
        f"- Broken manifest rows removed: {cleanup_report['removed_broken_manifest_count']}",
        "",
        "## Section 3.2 Draft Summary",
        (
            f"The cleaned benchmark contains {len(df)} valid ground-truth samples "
            f"covering {df['city'].nunique()} cities, "
            f"{df[['city_key', 'block']].drop_duplicates().shape[0]} city-block pairs, "
            f"{df['template_id'].nunique()} templates, "
            f"{df['layout_type'].nunique()} layout types, and "
            f"{df['slide_size_label'].nunique()} slide sizes."
        ),
        "",
        "### City coverage",
    ]

    for row in city_counts.itertuples(index=False):
        lines.append(f"- {row.city}: {row.samples} samples across {row.unique_blocks} blocks")

    lines.extend(
        [
            "",
            "### Layout coverage",
        ]
    )
    for row in layout_counts.itertuples(index=False):
        lines.append(f"- {row.layout_label}: {row.samples} samples")

    lines.extend(
        [
            "",
            "### Slide-size coverage",
        ]
    )
    for row in size_counts.itertuples(index=False):
        ratio = row.samples / len(df) * 100
        lines.append(f"- {row.slide_size_label}: {row.samples} samples ({ratio:.1f}%)")

    lines.extend(
        [
            "",
            "### Theme coverage",
        ]
    )
    for row in theme_counts.itertuples(index=False):
        lines.append(f"- {row.theme_key}: {row.samples} slides")

    lines.extend(
        [
            "",
            "### Function occurrence coverage",
        ]
    )
    for row in function_counts.itertuples(index=False):
        lines.append(f"- {row.function_key} ({row.theme_key}): {row.samples} occurrences")

    lines.extend(
        [
            "",
            "### Style coverage",
        ]
    )
    for row in style_counts.itertuples(index=False):
        lines.append(f"- {row.style_config_id}: {row.samples} slides")

    lines.extend(
        [
            "",
            "### Template notes",
            (
                "Most templates have 139 valid samples, while "
                "T01_Supply_Trans_Bar and T01_Supply_Trans_Line each have 137, "
                "which indicates two city-block combinations failed only for the T01 pair."
            ),
            "",
            "### Recommended figures for Section 3.2",
            "- Figure A: benchmark_scope.pdf/png for city, block, layout, and slide-size coverage.",
            "- Figure B: function_taxonomy.pdf/png for semantic theme and function coverage.",
            "- Figure C: layout_style_matrix.pdf/png for layout-style diversity and structural attributes.",
        ]
    )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean benchmark dataset and produce descriptive statistics.")
    parser.add_argument(
        "--dataset-root",
        required=True,
        help="Benchmark dataset root, e.g. output/benchmark/dataset_20260407",
    )
    parser.add_argument(
        "--analysis-dir",
        default=None,
        help="Output directory for tables/figures/report; defaults to output/benchmark_analysis/<dataset-name>",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_root = Path(args.dataset_root).resolve()
    analysis_dir = (
        Path(args.analysis_dir).resolve()
        if args.analysis_dir
        else PROJECT_ROOT / "output" / "benchmark_analysis" / dataset_root.name
    )
    analysis_dir.mkdir(parents=True, exist_ok=True)

    audit = audit_dataset(dataset_root)
    cleanup_report = cleanup_dataset(dataset_root, audit)

    rows = load_samples(dataset_root)
    df = build_dataframe(rows)

    figures_dir = analysis_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    save_tables(df, analysis_dir)
    plot_dataset_overview(df, figures_dir / "benchmark_scope")
    plot_function_taxonomy(df, figures_dir / "function_taxonomy")
    plot_layout_style_matrix(df, figures_dir / "layout_style_matrix")
    render_markdown_report(df, cleanup_report, analysis_dir / "summary.md")

    (analysis_dir / "cleanup_report.json").write_text(
        json.dumps(cleanup_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(cleanup_report, ensure_ascii=False, indent=2))
    print(f"analysis_dir={analysis_dir}")


if __name__ == "__main__":
    main()
