from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import func, select

from . import assessment, database as db
from .auth import Actor
from .contracts import CandidateCreate, InterviewCreate, JobCreate, Object, TurnInput
from .domain import fixture_competencies
from .evals import run_evals
from .safety import consent
from .service import Service, object_value
from .settings import ROOT, Settings


def seed(service: Service) -> Object:
    actor = Actor("system", "fixture-seed", "合成种子")
    with service.database.unit_of_work() as connection:
        if db.scalar(connection, select(func.count()).select_from(db.jobs)):
            return {"seeded": False, "reason": "database_not_empty"}
        people: list[tuple[str, str]] = []
        for index, title in enumerate(["研究生校招研发工程师", "研究生校招数据分析师", "研究生校招测试工程师"]):
            job = service.create_job(connection, JobCreate(title=title, jd_text="面向研究生的岗位，重视研究实践、问题分析、学习成长与岗位协作，通过个人行为与量化结果验证能力。", recruitment_track="graduate_campus"), actor).payload
            service.save_competencies(connection, str(job["id"]), fixture_competencies(True), True, actor)
            for number in range(3):
                person = service.create_candidate(connection, CandidateCreate(job_id=str(job["id"]), full_name=f"合成候选人{index + 1}-{number + 1}"), actor).payload
                people.append((str(job["id"]), str(person["id"])))
        states: list[str] = []
        for index, (job_id, candidate_id) in enumerate(people[:4]):
            created = service.create_interview(connection, InterviewCreate(job_id=job_id, candidate_id=candidate_id, duration_minutes=15), actor).payload
            identity = str(created["interviewId"])
            if index >= 1:
                version, _ = consent("text", False, "graduate_campus")
                service.submit_consent(connection, identity, version)
            if index >= 2:
                service.start(connection, identity)
            if index == 3:
                for _ in range(13):
                    service.turn(connection, identity, TurnInput(action="answer", content="我主导研究模块，个人负责实现和回归验证。我与同学沟通分歧并达成一致，将耗时降低40%，把验证机制复用到多个项目。"))
                service.finish(connection, identity)
                assessment.generate_report(service, connection, identity, False, actor)
            states.append(str(service.interview(connection, identity)["status"]))
        return {"seeded": True, "jobs": 3, "candidates": 9, "interviews": 4, "states": states}


def retention_command(settings: Settings, execute: bool) -> Object:
    if not settings.admin_key:
        raise ValueError("请通过环境变量配置ADMIN_API_KEY，密钥不得放入命令行参数")
    with httpx.Client(base_url=settings.app_base_url.rstrip("/"), headers={"Authorization": f"Bearer {settings.admin_key}"}, timeout=60) as client:
        response = client.get("/api/admin/retention")
        response.raise_for_status()
        workspace = object_value(response.json())
        preview = object_value(workspace["preview"])
        if not execute:
            return {"executed": False, "cutoffAt": preview["cutoffAt"], "counts": preview["counts"], "hasMore": preview["hasMore"]}
        response = client.post("/api/admin/retention/run", json={"previewToken": preview["previewToken"], "reason": "部署定时任务按预览清理到期资料"})
        response.raise_for_status()
        return {"executed": True, **object_value(response.json()), "hadMoreAtPreview": preview["hasMore"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="AI interviewer Python administration")
    parser.add_argument("command", choices=["migrate", "seed", "ids", "evals", "openapi", "retention-preview", "retention-run", "import-snapshot"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--quarantine-unconsented", action="store_true", help="将缺少历史同意的完整场次保存在离线快照，不导入在线业务库")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "evals":
        result = run_evals()
    elif args.command.startswith("retention-"):
        if args.command == "retention-run" and not args.execute:
            parser.error("retention-run需要显式--execute")
        result = retention_command(settings, args.command == "retention-run")
    elif args.command == "openapi":
        from .main import create_app
        schema = create_app(Settings(sqlite_path=":memory:")).openapi()
        output = args.file or ROOT / "docs/openapi.json"
        output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        result = {"written": str(output), "paths": len(schema["paths"])}
    else:
        database = db.Database(settings)
        try:
            database.migrate()
            service = Service(settings, database)
            if args.command == "migrate":
                result = {"migrated": True, "driver": "postgres" if database.postgres else "sqlite"}
            elif args.command == "seed":
                result = seed(service)
            elif args.command == "import-snapshot":
                if not args.file:
                    parser.error("import-snapshot需要--file，目标库必须为空")
                from .snapshot import import_snapshot
                result = import_snapshot(database, args.file, args.quarantine_unconsented)
            else:
                with database.unit_of_work() as connection:
                    result = {"jobs": [str(row["id"]) for row in db.rows(connection, select(db.jobs.c.id))],
                              "candidates": [str(row["id"]) for row in db.rows(connection, select(db.candidates.c.id))]}
        finally:
            database.close()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as error:
        print(json.dumps({"error": "治理HTTP请求失败", "type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, RuntimeError) as error:
        print(json.dumps({"error": "COMMAND_FAILED", "message": "请核对配置、文件和空目标库要求；原库未自动重置", "type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
