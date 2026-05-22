"""
charts.base
===========
Abstract base class for all Plotly chart components.

Design goals
------------
- Enforce a uniform interface: every chart exposes a ``render`` method
  that returns a ``plotly.graph_objects.Figure``.
- Keep the Streamlit layer chart-agnostic: ``st.plotly_chart(chart.render(...))``
  is the only pattern the UI layer needs to know.
- Adding a new chart type requires only creating a new subclass;
  no existing code is modified.

Planned extensions (do not implement yet)
-----------------------------------------
- ``render_panel(figures)`` : composite multi-panel layout (e.g. price + RSI)
- ``apply_theme(fig, theme)`` : apply a named visual theme to any figure
"""

from abc import ABC, abstractmethod

import pandas as pd


class ChartBase(ABC):
    """
    Abstract base class for all dashboard chart components.

    Concrete subclasses must implement the ``render`` method, which builds
    a Plotly figure and renders it directly via ``st.plotly_chart``.
    """

    @abstractmethod
    def render(self, df: pd.DataFrame) -> None:
        """
        Build and render the chart for this component.

        Parameters
        ----------
        df : pd.DataFrame
            Canonical OHLCV DataFrame produced by ``data.processor``.
            Subclasses must return early silently when ``df`` is empty.

        Returns
        -------
        None
            Renders directly into the active Streamlit container via
            ``st.plotly_chart(use_container_width=True)``.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
