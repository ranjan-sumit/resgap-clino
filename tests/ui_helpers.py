"""Drive the page-style flows (Settings, New analysis wizard) from AppTest."""
import utils.database as db
from utils import project_store

PID = db.DEFAULT_PROJECT_ID


def click(at, key):
    at.button(key=key).click().run()
    return at


def open_settings(at):
    return click(at, "settings_btn")


def open_wizard(at):
    return click(at, "new_analysis_btn")


def tick_stored_papers(at, project_id, ids):
    for pid in ids:
        at.checkbox(key=f"wiz_use_{project_id}_{pid}").check()
    at.run()
    return at


def next_step(at):
    return click(at, "wiz_next")


def wizard_to_review(at, project_id=PID, ids=()):
    """Opens the wizard, ticks the given stored papers, and moves to step 4."""
    open_wizard(at)
    tick_stored_papers(at, project_id, ids)
    for _ in range(3):
        next_step(at)
    return at


def store_papers(n=2, project_id=PID):
    from tests.test_unreadable_pdfs import _text_pdf
    return project_store.save_papers(project_id, [(f"p{i}.pdf", _text_pdf(f"paper {i}")) for i in range(n)])


def texts(at):
    return " ".join(str(getattr(e, "value", "")) for e in (*at.markdown, *at.caption, *at.info, *at.warning,
                                                            *at.success, *at.error))
