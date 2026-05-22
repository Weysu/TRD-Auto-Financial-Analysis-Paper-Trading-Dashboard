"""
ui package
==========
Streamlit UI layer — sidebar controls and main layout composition.

Responsibilities
----------------
- Render all interactive controls (asset selector, time-range picker).
- Return user selections as plain Python values consumed by ``app.py``.
- Compose the main content area by calling chart render functions.
- Contains zero data-fetching or processing logic.

Modules
-------
ui.sidebar  : Left-panel controls (asset dropdown, time-range buttons).
ui.layout   : Main content area layout (chart grid, metric row).

Planned extensions (do not implement yet)
-----------------------------------------
- ui.portfolio  : Portfolio summary panel
- ui.alerts     : Alert configuration panel
- ui.settings   : Theme / display preferences panel
"""
