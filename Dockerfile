# NetHeal-Agent Docker Image
# Multi-stage build: compile dependencies, then create minimal runtime
# Based on Co-Sight + NetHeal P0/P1/P2 enhancements (dev branch)

FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Fix phx-class-registry compatibility with lagent
RUN pip install --no-cache-dir "phx-class-registry>=3.0,<4.0" --force-reinstall --no-deps


# ---- Runtime stage ----
FROM python:3.13-slim

LABEL org.opencontainers.image.title="NetHeal-Agent"
LABEL org.opencontainers.image.description="5G Campus Private Network Multi-Agent Fault Diagnosis & Self-Healing System"
LABEL org.opencontainers.image.source="https://github.com/zzl111210/co-sight"
LABEL org.opencontainers.image.version="1.0.0"

WORKDIR /app

# Install runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages

# Copy application code
COPY app/ ./app/
COPY config/ ./config/
COPY cosight_server/ ./cosight_server/
COPY docs/ ./docs/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY tools/ ./tools/
COPY CoSight.py llm.py setup.py MANIFEST.in .env_template requirements.txt ./

# Create data directories
RUN mkdir -p /app/work_space /app/upload_files /app/logs

# Patch phx-class-registry for Python 3.13 compatibility
RUN python -c "
import sys
from pathlib import Path
p = Path(sys.prefix) / 'lib' / 'python3.13' / 'site-packages' / 'class_registry' / 'entry_points.py'
if p.is_file():
    content = p.read_text()
    content = content.replace(
        'from pkg_resources import iter_entry_points',
        '''try:
    from pkg_resources import iter_entry_points
except ImportError:
    from importlib.metadata import entry_points
    def iter_entry_points(group):
        eps = entry_points()
        if hasattr(eps, \"select\"):
            return eps.select(group=group)
        else:
            return eps.get(group, [])'''
    )
    p.write_text(content)
    print('Patched class_registry/entry_points.py')
"

# Patch lagent for empty docstring compatibility
RUN python -c "
import sys
from pathlib import Path
p = Path(sys.prefix) / 'lib' / 'python3.13' / 'site-packages' / 'lagent' / 'actions' / 'base_action.py'
if p.is_file():
    content = p.read_text()
    # Fix empty docstring crash
    content = content.replace(
        \"description=docs[0].value if docs[0].kind is DocstringSectionKind.text else ''\",
        \"description=docs[0].value if docs and docs[0].kind is DocstringSectionKind.text else ''\"
    )
    # Fix empty docstring in ToolMeta
    content = content.replace(
        \"description=Docstring(attrs.get('__doc__', '')).parse('google')[0].value)\",
        \"parsed = Docstring(attrs.get('__doc__', '')).parse('google'); desc_text = parsed[0].value if parsed else ''\" + chr(10) + \"        is_toolkit, tool_desc = True, dict(\" + chr(10) + \"            name=attrs.setdefault('__tool_name__', name),\" + chr(10) + \"            description=desc_text)\"
    )
    p.write_text(content)
    print('Patched lagent/actions/base_action.py')
"

# Expose port
EXPOSE 7788

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:7788/api/netheal/v1/health || exit 1

# Default command
CMD ["python", "cosight_server/deep_research/main.py"]
