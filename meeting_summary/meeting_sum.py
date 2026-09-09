import importlib
from pathlib import Path

from dotenv import load_dotenv
import streamlit as st

from scenarios import list_scenarios
from scenarios.live_mic import stop_live_capture
import presentation as ui

load_dotenv(Path(__file__).resolve().parent / ".env")
st.set_page_config(
    page_title="AVIA | Audio and Visual Studio",
    page_icon=":material/graphic_eq:",
    layout="wide",
    initial_sidebar_state="auto",
)

_DEF_MODULES = [
    "scenarios.live_mic",
    "scenarios.audio_file_summary",
    "scenarios.image_analysis",
]
for module in _DEF_MODULES:
    importlib.import_module(module)
scenarios = list_scenarios()
st.session_state.setdefault("selected_scenario", None)


def navigate(target):
    if st.session_state.selected_scenario == "live_mic" and not stop_live_capture():
        st.error("Capture shutdown is not yet confirmed. Stay here until Speech has stopped.")
        return
    st.session_state.selected_scenario = target
    st.rerun()


with st.sidebar:
    ui.brand()
    with st.container(key="avia_nav"):
        st.caption("WORKSPACES")
        if st.button(
            "Overview", icon=":material/grid_view:", key="nav_home",
            type="primary" if st.session_state.selected_scenario is None else "secondary",
            disabled=st.session_state.selected_scenario is None,
            use_container_width=True,
        ):
            navigate(None)
        for key in [*ui.WORKSPACES, *(key for key in scenarios if key not in ui.WORKSPACES)]:
            if key not in scenarios:
                continue
            display = ui.WORKSPACES.get(key, {})
            if st.button(
                display.get("nav", scenarios[key]["title"]),
                icon=display.get("material_icon", ":material/widgets:"),
                key=f"nav_{key}",
                type="primary" if st.session_state.selected_scenario == key else "secondary",
                disabled=st.session_state.selected_scenario == key,
                use_container_width=True,
            ):
                navigate(key)
    st.divider()
    default_theme = "Dark" if st.query_params.get("clawpilotTheme") == "dark" else "Light"
    st.session_state.setdefault("avia_appearance", st.session_state.get("avia_theme", default_theme))
    appearance = st.radio("Appearance", ["Light", "Dark"], horizontal=True, key="avia_appearance")
    st.session_state["avia_theme"] = appearance
    st.caption("Your local studio. Cloud services use the configured server identity.")

ui.apply_theme(appearance)
selected = st.session_state.selected_scenario
ui.topbar(ui.WORKSPACES.get(selected, {}).get("nav", scenarios[selected]["title"] if selected in scenarios else "Overview"))
if selected in scenarios:
    if st.button("Back to scenarios", icon=":material/arrow_back:", key="back_to_scenarios"):
        navigate(None)
    meta = scenarios[selected]
    ui.workspace_header(selected, meta["title"], meta["description"])
    meta["render"]()
else:
    with st.container(key="avia_hero"):
        intro, artwork = st.columns([1.2, 1], vertical_alignment="center")
        with intro:
            ui.hero()
            if st.button(
                "Start with your audio", type="primary", icon=":material/arrow_forward:",
                key="hero_open_lab",
            ):
                navigate("audio_file_summary")
        with artwork:
            ui.workflow_illustration()
    ui.section_heading("What would you like to work on?", "Choose a focused workspace. Keep every step in context.")
    ordered = [key for key in ui.WORKSPACES if key in scenarios]
    ordered.extend(key for key in scenarios if key not in ui.WORKSPACES)
    with st.container(key="avia_workspace_grid"):
        for start in range(0, len(ordered), 3):
            row = ordered[start:start + 3]
            for key, column in zip(row, st.columns(len(row))):
                meta = scenarios[key]
                display = ui.WORKSPACES.get(key)
                with column, st.container(key=f"avia_workspace_{key}"):
                    if display:
                        ui.workspace_card(display)
                    else:
                        st.subheader(meta["title"])
                        st.write(meta["description"])
                        st.caption(meta["keywords"])
                    if st.button(
                        display["action"] if display else "Open workspace",
                        key=f"open_{key}",
                        type="secondary",
                        use_container_width=True,
                    ):
                        navigate(key)
    ui.footer()
