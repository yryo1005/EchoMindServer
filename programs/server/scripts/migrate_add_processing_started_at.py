"""`upload_records`テーブルに`processing_started_at`列を追加する一度限りの移行スクリプト．

`processing_started_at`列の追加前に作成された`upload_records`には，この列が
存在しない(`Base.metadata.create_all`は既存テーブルへの列追加を行わないため)．
既存の行には，バックフィルとして`created_at`の値を設定する(この移行以前のデータに
対する停滞判定の起点としては`created_at`で近似する他ないため)．

実行方法:
    .venv_ml/bin/python programs/server/scripts/migrate_add_processing_started_at.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import engine  # noqa: E402


def migrate() -> None:
    """`processing_started_at`列を追加し，既存行をバックフィルする関数．

    引数:
        なし
    戻り値:
        なし
    """
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE upload_records ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP"))
        result = conn.execute(
            text(
                "UPDATE upload_records SET processing_started_at = created_at "
                "WHERE processing_started_at IS NULL"
            )
        )
        conn.commit()
        print(f"{result.rowcount}件の既存レコードにprocessing_started_atをバックフィルしました．")


if __name__ == "__main__":
    migrate()
