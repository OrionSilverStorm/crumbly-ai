"""MLflow 3 tracing: spans per agent step and tool call, grouped per incident (tag + session), stored in UC when available."""
import functools
import logging

from backend.config import settings

log = logging.getLogger("crumbly.tracing")
# Set by init(): whether tracing is live, where traces go, and the experiment id for trace links.
_state = {"on": False, "location": "disabled", "experiment_id": None}


def init() -> None:
    """Point MLflow at the configured backend. UC trace tables first; the default experiment store as fallback."""
    if not settings.tracing_enabled:
        return
    try:
        import mlflow

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        exp = None
        if settings.mlflow_uc_traces:
            try:
                from mlflow.entities.trace_location import UnityCatalog

                # Needs MLFLOW_TRACING_SQL_WAREHOUSE_ID in the environment and an absolute experiment path.
                exp = mlflow.set_experiment(
                    experiment_name=settings.mlflow_experiment,
                    trace_location=UnityCatalog(catalog_name=settings.uc_catalog, schema_name=settings.uc_schema),
                )
                _state["location"] = f"unity_catalog:{settings.uc_catalog}.{settings.uc_schema}"
            except Exception as e:  # documented fallback: default experiment trace store
                log.warning("UC trace location unavailable (%s); using the experiment trace store", e)
        if exp is None:
            exp = mlflow.set_experiment(settings.mlflow_experiment)
            _state["location"] = "experiment"
        _state.update(on=True, experiment_id=exp.experiment_id)
    except Exception as e:
        log.warning("Tracing disabled: %s", e)


def status() -> dict:
    """Where traces are going (shown in the UI's 'behind the scenes' card)."""
    return dict(_state)


def traced(name: str | None = None, span_type: str = "CHAIN"):
    """Decorator: wrap a function in an MLflow span (a root span becomes a trace). No-op if tracing is off."""

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            if not _state["on"]:
                return fn(*a, **kw)
            import mlflow

            return mlflow.trace(name=name or fn.__name__, span_type=span_type)(fn)(*a, **kw)

        return inner

    return wrap


def tag_incident(incident_id: str | None) -> None:
    """Tag the active trace with the incident (and group traces into one MLflow session per incident)."""
    if not (_state["on"] and incident_id):
        return
    try:
        import mlflow

        mlflow.update_current_trace(tags={"incident_id": incident_id}, session_id=incident_id)
    except Exception as e:  # tagging must never break the business flow
        log.debug("trace tag failed: %s", e)


def active_trace_id() -> str | None:
    """Trace id of the current request, stored on events so the UI can link to it."""
    if not _state["on"]:
        return None
    import mlflow

    return mlflow.get_active_trace_id()


def trace_url(trace_id: str | None) -> str | None:
    """Browser link to a trace on Databricks (the final hex part of a UC trace id); None locally."""
    if not trace_id or not settings.mlflow_tracking_uri.startswith("databricks"):
        return None
    from databricks.sdk.core import Config

    return f"{Config().host}/ml/experiments/{_state['experiment_id']}/traces/{trace_id.split('/')[-1]}"


def log_feedback(trace_id: str | None, reason: str, note: str | None, owner_id: str) -> bool:
    """Record the owner's rejection as human feedback on the relevant trace."""
    if not (_state["on"] and trace_id):
        return False
    try:
        import mlflow
        from mlflow.entities import AssessmentSource

        mlflow.log_feedback(
            trace_id=trace_id, name="owner_rejection", value=reason, rationale=note or None,
            source=AssessmentSource(source_type="HUMAN", source_id=owner_id),
        )
        return True
    except Exception as e:
        log.warning("log_feedback failed: %s", e)
        return False
