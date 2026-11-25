"""The 008 migration on a database that already holds data (spec 008, T007).

Run on an empty database the data statements prove nothing, so rows are
inserted between the two upgrades: existing product images must read as
photos, existing idea entries must survive (an id in ``generation_job_id``
that points at no job is cleared so the foreign key can be created), and the
downgrade must give the previous schema back without losing those rows.
"""

import os
import uuid

import pytest
from alembic import command
from sqlalchemy import text

from tests.integration.migration_support import (
    alembic_against,
    scratch_database_at,
    templates_needed,
)

PARENT = "printer_serial_v1"
REVISION = "genai_v1"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


pytestmark = pytest.mark.skipif(
    "postgres" not in _database_url(),
    reason="the 008 migration needs PostgreSQL (RLS policies, JSONB); set DATABASE_URL",
)


templates_needed(PARENT)


@pytest.fixture(scope="module")
def scratch():
    with scratch_database_at(PARENT, "genai_mig") as (engine, url):
        ids = {k: uuid.uuid4() for k in ("tenant", "idea", "entry", "orphan", "product", "image")}
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, is_active, settings, created_at, updated_at)"
                    " VALUES (:tenant, 'Mig', 'mig-shop', true, CAST('{}' AS JSONB), now(), now())"
                ),
                ids,
            )
            conn.execute(
                text("INSERT INTO ideas (id, tenant_id, title) VALUES (:idea, :tenant, 'Clip')"),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO idea_entries (id, tenant_id, idea_id, kind, body) VALUES"
                    " (:entry, :tenant, :idea, 'note', 'plain note')"
                ),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO idea_entries (id, tenant_id, idea_id, kind, body, generation_job_id)"
                    " VALUES (:orphan, :tenant, :idea, 'note', 'points at nothing', gen_random_uuid())"
                ),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO products (id, tenant_id, sku, name) VALUES"
                    " (:product, :tenant, 'MIG-1', 'Mig product')"
                ),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO product_images (id, tenant_id, product_id, image_url, created_at,"
                    " updated_at) VALUES (:image, :tenant, :product, '/uploads/products/a.png',"
                    " now(), now())"
                ),
                ids,
            )
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)
        yield engine, url, ids


def test_existing_product_images_are_photos(scratch):
    engine, _, ids = scratch
    with engine.connect() as conn:
        origin = conn.execute(
            text("SELECT origin FROM product_images WHERE id = :image"), ids
        ).scalar_one()
    assert origin == "photo"


def test_idea_entries_survive_and_orphans_are_cleared(scratch):
    engine, _, ids = scratch
    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                text("SELECT body, generation_job_id FROM idea_entries WHERE idea_id = :idea"), ids
            ).all()
        )
    assert rows == {"plain note": None, "points at nothing": None}


def test_jobs_show_the_real_item_unless_told_otherwise(scratch):
    """A job row written without the flag (as before T098) reads as showing the real item."""
    engine, _, ids = scratch
    job_id = uuid.uuid4()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO generation_jobs (id, tenant_id, capability, provider, model_ref,"
                " model_version, inputs, seed, price_snapshot) VALUES (:job, :tenant,"
                " 'upscale', 'replicate', 'o/m', 'official', CAST('{}' AS JSONB), 1,"
                " CAST('{}' AS JSONB))"
            ),
            {**ids, "job": job_id},
        )
        flag = conn.execute(
            text("SELECT shows_real_item FROM generation_jobs WHERE id = :job"), {"job": job_id}
        ).scalar_one()
        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_name ="
                " 'generation_jobs' AND column_name = 'shows_real_item'"
            )
        ).scalar_one()
        conn.execute(text("DELETE FROM generation_jobs WHERE id = :job"), {"job": job_id})
    assert flag is True
    assert nullable == "NO"


def test_uploads_show_the_real_item_unless_told_otherwise(scratch):
    """T107: an asset row written without the flag (a direct upload) shows the real item."""
    engine, _, ids = scratch
    asset = uuid.uuid4()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :tenant, false)"),
                     {"tenant": str(ids["tenant"])})  # fmt: skip
        conn.execute(
            text(
                "INSERT INTO genai_assets (id, tenant_id, source, kind, storage_url, content_type)"
                " VALUES (:asset, :tenant, 'upload', 'image', '/uploads/generations/x/b.png',"
                " 'image/png')"
            ),
            {**ids, "asset": asset},
        )
        flag = conn.execute(
            text("SELECT shows_real_item FROM genai_assets WHERE id = :asset"), {"asset": asset}
        ).scalar_one()
        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_name ="
                " 'genai_assets' AND column_name = 'shows_real_item'"
            )
        ).scalar_one()
        conn.execute(text("DELETE FROM genai_assets WHERE id = :asset"), {"asset": asset})
    assert flag is True
    assert nullable == "NO"


def test_new_tables_are_tenant_isolated(scratch):
    engine, _, _ = scratch
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN"
                " ('generation_jobs', 'genai_assets', 'genai_adoptions')"
            )
        ).all()
    assert sorted(r[0] for r in rows) == ["genai_adoptions", "genai_assets", "generation_jobs"]
    assert all(r[1] and r[2] for r in rows)


def test_origin_is_checked(scratch):
    engine, _, ids = scratch
    with engine.connect() as conn, pytest.raises(Exception, match="ck_product_images_origin"):
        conn.execute(text("UPDATE product_images SET origin = 'scan' WHERE id = :image"), ids)


def test_adoption_names_at_most_one_result(scratch):
    """F8: CHECK ck_genai_adoptions_one_result refuses two result FKs on one adoption."""
    engine, _, ids = scratch
    asset = uuid.uuid4()
    params = {**ids, "asset": asset}
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :tenant, false)"),
                     {"tenant": str(ids["tenant"])})  # fmt: skip
        conn.execute(
            text(
                "INSERT INTO genai_assets (id, tenant_id, source, kind, storage_url, content_type)"
                " VALUES (:asset, :tenant, 'upload', 'image', '/uploads/generations/x/a.png',"
                " 'image/png')"
            ),
            params,
        )
        conn.execute(
            text(
                "INSERT INTO genai_adoptions (id, tenant_id, asset_id, owner_type, owner_id,"
                " idea_entry_id) VALUES (gen_random_uuid(), :tenant, :asset, 'idea', :idea, :entry)"
            ),
            params,
        )
        with pytest.raises(Exception, match="ck_genai_adoptions_one_result"):
            conn.execute(
                text(
                    "INSERT INTO genai_adoptions (id, tenant_id, asset_id, owner_type, owner_id,"
                    " idea_entry_id, product_image_id) VALUES (gen_random_uuid(), :tenant,"
                    " :asset, 'product', :product, :entry, :image)"
                ),
                params,
            )
        conn.execute(text("DELETE FROM genai_assets WHERE id = :asset"), params)


def test_downgrade_keeps_the_rows(scratch):
    engine, url, ids = scratch
    with alembic_against(url) as config:
        command.downgrade(config, PARENT)
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT count(*) FROM pg_class WHERE relname = 'generation_jobs'")
        ).scalar_one()
        entries = conn.execute(
            text("SELECT count(*) FROM idea_entries WHERE idea_id = :idea"), ids
        ).scalar_one()
        images = conn.execute(text("SELECT count(*) FROM product_images")).scalar_one()
    assert tables == 0
    assert entries == 2
    assert images == 1
    with alembic_against(url) as config:
        command.upgrade(config, REVISION)
