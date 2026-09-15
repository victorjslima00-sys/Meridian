"""
Validação de integridade e consistência dos lockfiles e infraestrutura reproduzível (WS-C).
Garante:
1. Política VERSION-LOCKED (NOT HASH-VERIFIED) explicitada;
2. Ausência de claims fraudulentos de SHA-256 hash;
3. Presença obrigatória de ferramentas de dev (pytest, flake8, coverage, httpx, genetic_algorithm) no dev lock;
4. Todo pacote de requirements.lock presente em requirements-dev.lock com a mesma versão;
5. Dockerfile multi-stage com Node 22 builder e Nginx runtime configurados;
6. docker-compose sem execução de npm ci/npm run build em runtime.
"""
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_lock_files_exist_and_declare_policy():
    req_lock = REPO_ROOT / "requirements.lock"
    dev_lock = REPO_ROOT / "requirements-dev.lock"
    
    assert req_lock.exists(), "requirements.lock deve existir no repositório"
    assert dev_lock.exists(), "requirements-dev.lock deve existir no repositório"
    
    req_content = req_lock.read_text(encoding="utf-8")
    dev_content = dev_lock.read_text(encoding="utf-8")
    
    # Validação da política
    assert "VERSION-LOCKED" in req_content
    assert "NOT HASH-VERIFIED" in req_content
    assert "VERSION-LOCKED" in dev_content
    assert "NOT HASH-VERIFIED" in dev_content
    
    # Garante ausência de hashes falsificados
    assert "--hash" not in req_content
    assert "--hash" not in dev_content


def _parse_lock_packages(path: Path):
    packages = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # formato: pkg==ver ou pkg==ver; markers
        pkg_part = line.split(";")[0].strip()
        if "==" in pkg_part:
            name, ver = pkg_part.split("==", 1)
            packages[name.lower().replace("_", "-")] = ver
    return packages


def test_dev_lock_contains_all_runtime_packages():
    req_lock = REPO_ROOT / "requirements.lock"
    dev_lock = REPO_ROOT / "requirements-dev.lock"
    
    runtime_pkgs = _parse_lock_packages(req_lock)
    dev_pkgs = _parse_lock_packages(dev_lock)
    
    missing = []
    mismatched = []
    for pkg, ver in runtime_pkgs.items():
        if pkg not in dev_pkgs:
            missing.append(pkg)
        elif dev_pkgs[pkg] != ver:
            mismatched.append(f"{pkg}: runtime={ver} vs dev={dev_pkgs[pkg]}")
            
    assert not missing, f"Pacotes do runtime ausentes no requirements-dev.lock: {missing}"
    assert not mismatched, f"Versões divergentes entre requirements.lock e dev lock: {mismatched}"


def test_dev_lock_contains_mandatory_dev_tooling():
    dev_lock = REPO_ROOT / "requirements-dev.lock"
    dev_pkgs = _parse_lock_packages(dev_lock)
    
    mandatory = [
        "pytest",
        "pytest-asyncio",
        "pytest-cov",
        "flake8",
        "httpx",
        "genetic-algorithm",
    ]
    
    missing = [m for m in mandatory if m not in dev_pkgs]
    assert not missing, f"Ferramentas de desenvolvimento mandatórias ausentes em requirements-dev.lock: {missing}"


def test_frontend_dockerfile_multi_stage_structure():
    dockerfile = REPO_ROOT / "frontend" / "Dockerfile"
    assert dockerfile.exists(), "frontend/Dockerfile deve existir"
    
    content = dockerfile.read_text(encoding="utf-8")
    assert "node:22-alpine" in content or "node:22" in content, "Builder deve usar Node 22"
    assert "AS builder" in content, "Dockerfile deve conter estágio builder"
    assert "npm ci" in content, "Builder deve executar npm ci"
    assert "npm run build" in content, "Builder deve compilar assets com npm run build"
    assert "nginx:alpine" in content or "nginx" in content, "Runtime deve usar servidor estático nginx"
    assert "--from=builder" in content, "Runtime deve copiar dist construído pelo builder"


def test_docker_compose_does_not_execute_npm_ci_on_startup():
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml deve existir"
    
    content = compose_file.read_text(encoding="utf-8")
    assert "npm ci" not in content, "docker-compose não deve executar npm ci em tempo de execução"
    assert "npm run build" not in content, "docker-compose não deve executar npm run build em tempo de execução"
