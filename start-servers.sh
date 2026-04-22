#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/.run-logs"
mkdir -p "${LOG_DIR}"

CONDA_ENV="${CONDA_ENV:-collab}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-5180}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5179}"

BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
BACKEND_PID_FILE="${LOG_DIR}/backend.pid"
FRONTEND_PID_FILE="${LOG_DIR}/frontend.pid"

cleanup() {
  local code="$?"
  if [[ -f "${BACKEND_PID_FILE}" ]]; then
    local backend_pid
    backend_pid="$(cat "${BACKEND_PID_FILE}")"
    if kill -0 "${backend_pid}" >/dev/null 2>&1; then
      kill "${backend_pid}" >/dev/null 2>&1 || true
    fi
    rm -f "${BACKEND_PID_FILE}"
  fi
  if [[ -f "${FRONTEND_PID_FILE}" ]]; then
    local frontend_pid
    frontend_pid="$(cat "${FRONTEND_PID_FILE}")"
    if kill -0 "${frontend_pid}" >/dev/null 2>&1; then
      kill "${frontend_pid}" >/dev/null 2>&1 || true
    fi
    rm -f "${FRONTEND_PID_FILE}"
  fi
  exit "${code}"
}

trap cleanup INT TERM EXIT

kill_port_if_needed() {
  local port="$1"
  local label="$2"
  if ! command -v lsof >/dev/null 2>&1; then
    echo "Warning: lsof not found; cannot auto-kill processes on port ${port}."
    return
  fi
  local pids
  pids="$(lsof -ti tcp:${port} || true)"
  if [[ -z "${pids}" ]]; then
    return
  fi
  echo "Stopping existing ${label} process(es) on port ${port}: ${pids}"
  kill ${pids} >/dev/null 2>&1 || true
  sleep 0.7
  local still_up
  still_up="$(lsof -ti tcp:${port} || true)"
  if [[ -n "${still_up}" ]]; then
    kill -9 ${still_up} >/dev/null 2>&1 || true
  fi
}

if ! command -v conda >/dev/null 2>&1; then
  echo "Error: conda is required but not found in PATH."
  exit 1
fi

echo "Checking Python in conda env '${CONDA_ENV}'..."
if ! conda run -n "${CONDA_ENV}" python -V >/dev/null 2>&1; then
  echo "Error: conda env '${CONDA_ENV}' does not have a runnable python."
  echo "Fix with: conda install -n ${CONDA_ENV} python"
  exit 1
fi

echo "Checking npm in conda env '${CONDA_ENV}'..."
if ! conda run -n "${CONDA_ENV}" npm -v >/dev/null 2>&1; then
  echo "Error: npm is not available in conda env '${CONDA_ENV}'."
  echo "Fix with: conda install -n ${CONDA_ENV} -c conda-forge nodejs"
  echo "Then run: conda run -n ${CONDA_ENV} npm --prefix ${ROOT_DIR}/client install"
  exit 1
fi

kill_port_if_needed "${BACKEND_PORT}" "backend"
kill_port_if_needed "${FRONTEND_PORT}" "frontend"

echo "Starting backend on http://${BACKEND_HOST}:${BACKEND_PORT} ..."
conda run -n "${CONDA_ENV}" \
  --no-capture-output \
  python -m uvicorn server.app.main:app \
  --host "${BACKEND_HOST}" \
  --port "${BACKEND_PORT}" \
  --reload >"${BACKEND_LOG}" 2>&1 &
BACKEND_PID=$!
echo "${BACKEND_PID}" >"${BACKEND_PID_FILE}"

echo "Starting frontend on http://${FRONTEND_HOST}:${FRONTEND_PORT} ..."
(
  VITE_DEV_API_TARGET="http://${BACKEND_HOST}:${BACKEND_PORT}" \
    conda run -n "${CONDA_ENV}" --no-capture-output npm --prefix "${ROOT_DIR}/client" run dev -- \
    --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort
) >"${FRONTEND_LOG}" 2>&1 &
FRONTEND_PID=$!
echo "${FRONTEND_PID}" >"${FRONTEND_PID_FILE}"

sleep 1

if ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
  echo "Backend failed to start. Check ${BACKEND_LOG}"
  exit 1
fi

if ! kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
  echo "Frontend failed to start. Check ${FRONTEND_LOG}"
  exit 1
fi

echo "Waiting for backend health..."
for _ in {1..30}; do
  if curl -sf "http://${BACKEND_HOST}:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! curl -sf "http://${BACKEND_HOST}:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "Backend process started but health check failed."
  echo "Last backend logs:"
  tail -n 80 "${BACKEND_LOG}" || true
  exit 1
fi

echo
echo "Servers running:"
echo "  Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "  Backend:  http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "Logs:"
echo "  ${BACKEND_LOG}"
echo "  ${FRONTEND_LOG}"
echo
echo "Press Ctrl+C to stop both."

wait
