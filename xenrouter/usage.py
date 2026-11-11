"""
Persistent daily and monthly token/request usage analytics tracker for Xenrouter.
Stores aggregated request and token counts in SQLite so usage persists across restarts.
"""

from datetime import datetime
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple, Union


def get_default_usage_db_path() -> Path:
    """Return the default persistent SQLite path under ~/.xenrouter/usage.db."""
    return Path.home() / ".xenrouter" / "usage.db"


def _empty_totals() -> Dict[str, int]:
    return {
        "requests": 0,
        "successful": 0,
        "failed": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def _row_to_totals(row: Tuple[Any, ...]) -> Dict[str, int]:
    return {
        "requests": int(row[0] or 0),
        "successful": int(row[1] or 0),
        "failed": int(row[2] or 0),
        "prompt_tokens": int(row[3] or 0),
        "completion_tokens": int(row[4] or 0),
        "total_tokens": int(row[5] or 0),
    }


class UsageTracker:
    """Thread-safe persistent daily and monthly inference usage recorder."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self._lock = threading.Lock()
        if db_path is None:
            if "PYTEST_CURRENT_TEST" in os.environ:
                self._db_target = ":memory:"
            else:
                self._db_target = str(get_default_usage_db_path())
        else:
            self._db_target = str(db_path)

        if self._db_target != ":memory:":
            Path(self._db_target).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_target, check_same_thread=False, timeout=5.0)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            if self._db_target != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_records (
                    usage_date TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    successful_requests INTEGER NOT NULL DEFAULT 0,
                    failed_requests INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (usage_date, provider, model)
                );
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_records_date ON usage_records(usage_date);"
            )
            self._conn.commit()

    def record(
        self,
        success: bool,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        usage_date: Optional[str] = None,
    ) -> None:
        """Persist a single request outcome and token counts into daily aggregation."""
        date_val = (usage_date or datetime.now().strftime("%Y-%m-%d")).strip()
        prov_val = (provider or "unrouted").strip() or "unrouted"
        model_val = (model or "unknown").strip() or "unknown"

        p_toks = max(0, int(prompt_tokens or 0))
        c_toks = max(0, int(completion_tokens or 0))
        t_toks = p_toks + c_toks
        ok_inc = 1 if success else 0
        err_inc = 0 if success else 1

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO usage_records (
                    usage_date, provider, model,
                    requests, successful_requests, failed_requests,
                    prompt_tokens, completion_tokens, total_tokens
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(usage_date, provider, model) DO UPDATE SET
                    requests = requests + 1,
                    successful_requests = successful_requests + excluded.successful_requests,
                    failed_requests = failed_requests + excluded.failed_requests,
                    prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                    completion_tokens = completion_tokens + excluded.completion_tokens,
                    total_tokens = total_tokens + excluded.total_tokens;
                """,
                (date_val, prov_val, model_val, ok_inc, err_inc, p_toks, c_toks, t_toks),
            )
            self._conn.commit()

    def _query_aggregate(self, where_sql: str = "", params: Tuple[Any, ...] = ()) -> Dict[str, int]:
        sql = (
            "SELECT COALESCE(SUM(requests), 0), COALESCE(SUM(successful_requests), 0), "
            "COALESCE(SUM(failed_requests), 0), COALESCE(SUM(prompt_tokens), 0), "
            "COALESCE(SUM(completion_tokens), 0), COALESCE(SUM(total_tokens), 0) "
            f"FROM usage_records {where_sql}"
        )
        cur = self._conn.execute(sql, params)
        row = cur.fetchone()
        return _row_to_totals(row) if row else _empty_totals()

    def _query_breakdown(
        self,
        group_expr: str,
        key_name: str,
        where_sql: str = "",
        params: Tuple[Any, ...] = (),
        order_by: str = "t_toks DESC, reqs DESC",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        sql = (
            f"SELECT {group_expr} AS grp_key, "
            "COALESCE(SUM(requests), 0) AS reqs, "
            "COALESCE(SUM(successful_requests), 0) AS ok_reqs, "
            "COALESCE(SUM(failed_requests), 0) AS err_reqs, "
            "COALESCE(SUM(prompt_tokens), 0) AS p_toks, "
            "COALESCE(SUM(completion_tokens), 0) AS c_toks, "
            "COALESCE(SUM(total_tokens), 0) AS t_toks "
            f"FROM usage_records {where_sql} "
            f"GROUP BY grp_key ORDER BY {order_by} LIMIT ?"
        )
        rows = self._conn.execute(sql, (*params, limit)).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            entry: Dict[str, Any] = {key_name: row[0]}
            entry.update(_row_to_totals(row[1:]))
            results.append(entry)
        return results

    def get_summary(
        self,
        days: int = 30,
        months: int = 12,
        ref_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return structured daily, monthly, all-time, provider, and model usage summaries."""
        today_str = (ref_date or datetime.now().strftime("%Y-%m-%d")).strip()
        month_str = today_str[:7]
        safe_days = max(1, min(365, int(days)))
        safe_months = max(1, min(60, int(months)))

        with self._lock:
            today_totals = self._query_aggregate("WHERE usage_date = ?", (today_str,))
            today_totals["date"] = today_str

            month_totals = self._query_aggregate("WHERE substr(usage_date, 1, 7) = ?", (month_str,))
            month_totals["month"] = month_str

            all_time = self._query_aggregate()

            daily = self._query_breakdown(
                "usage_date",
                "date",
                order_by="grp_key DESC",
                limit=safe_days,
            )
            monthly = self._query_breakdown(
                "substr(usage_date, 1, 7)",
                "month",
                order_by="grp_key DESC",
                limit=safe_months,
            )
            providers_today = self._query_breakdown(
                "provider",
                "provider",
                where_sql="WHERE usage_date = ?",
                params=(today_str,),
                order_by="t_toks DESC, reqs DESC",
                limit=50,
            )
            providers_month = self._query_breakdown(
                "provider",
                "provider",
                where_sql="WHERE substr(usage_date, 1, 7) = ?",
                params=(month_str,),
                order_by="t_toks DESC, reqs DESC",
                limit=50,
            )
            models_today = self._query_breakdown(
                "model",
                "model",
                where_sql="WHERE usage_date = ?",
                params=(today_str,),
                order_by="t_toks DESC, reqs DESC",
                limit=50,
            )
            models_month = self._query_breakdown(
                "model",
                "model",
                where_sql="WHERE substr(usage_date, 1, 7) = ?",
                params=(month_str,),
                order_by="t_toks DESC, reqs DESC",
                limit=50,
            )

        return {
            "today": today_totals,
            "this_month": month_totals,
            "all_time": all_time,
            "daily": daily,
            "monthly": monthly,
            "providers_today": providers_today,
            "providers_month": providers_month,
            "models_today": models_today,
            "models_month": models_month,
        }

    def close(self) -> None:
        """Close the underlying SQLite connection safely."""
        with self._lock:
            self._conn.close()
