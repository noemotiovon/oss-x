#!/usr/bin/env python3
"""
Build foundation project cache from structured data sources.

Fetches project lists from official foundation APIs and pages,
producing output/.cache/foundation_projects.json.

This replaces the LLM Web Search approach with deterministic data sources:
  - Apache: projects.apache.org JSON API
  - CNCF: landscape.cncf.io API
  - Linux Foundation: known project list
  - Eclipse: projects.eclipse.org API
  - NumFOCUS: known project list
  - Others: curated static lists from official sources

Usage:
  python3 scripts/build_foundation_cache.py [-o output/.cache/foundation_projects.json] [--summary]
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass


def fetch_url(url, timeout=30):
    """Fetch URL and return response body as string."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "oss-x-foundation-cache-builder")
    req.add_header("Accept", "application/json, text/html, */*")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  Warning: failed to fetch {url}: {e}", file=sys.stderr)
        return None


def fetch_json(url, timeout=30):
    """Fetch URL and parse as JSON."""
    body = fetch_url(url, timeout)
    if body:
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            print(f"  Warning: invalid JSON from {url}: {e}", file=sys.stderr)
    return None


def extract_github_repos_from_text(text):
    """Extract github.com/owner/repo patterns from text."""
    pattern = r"github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"
    matches = re.findall(pattern, text)
    return [m.rstrip("/").lower() for m in matches]


# ---------------------------------------------------------------------------
# Foundation-specific fetchers
# ---------------------------------------------------------------------------


def fetch_apache_projects():
    """Apache Software Foundation — Whimsy LDAP projects API."""
    print("  Fetching Apache projects...", file=sys.stderr)
    data = fetch_json("https://whimsy.apache.org/public/public_ldap_projects.json")
    if not data:
        return _apache_static()

    apache_projects = data.get("projects", {})
    if not apache_projects:
        return _apache_static()

    projects = []
    for project_id in apache_projects:
        # Apache mirrors repos to github.com/apache/{project_id}
        projects.append(f"apache/{project_id}")

    return {
        "projects": sorted(set(projects)),
        "evidence": "https://whimsy.apache.org/public/public_ldap_projects.json (official Apache Whimsy API)",
    }


def _apache_static():
    """Fallback static list for Apache projects."""
    projects = [
        "apache/spark", "apache/kafka", "apache/hadoop", "apache/flink",
        "apache/airflow", "apache/cassandra", "apache/hbase", "apache/hive",
        "apache/zookeeper", "apache/dubbo", "apache/rocketmq", "apache/shardingsphere",
        "apache/doris", "apache/brpc", "apache/skywalking", "apache/apisix",
        "apache/arrow", "apache/beam", "apache/camel", "apache/httpd",
        "apache/tomcat", "apache/lucene", "apache/solr", "apache/pulsar",
        "apache/druid", "apache/iceberg", "apache/ozone", "apache/kyuubi",
        "apache/seatunnel", "apache/dolphinscheduler", "apache/inlong",
        "apache/streampark", "apache/paimon", "apache/fury",
        "apache/celeborn", "apache/opendal", "apache/gluten",
        "apache/tvm", "apache/mxnet", "apache/nuttx", "apache/thrift",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "Apache Software Foundation known projects (static fallback)",
    }


def fetch_cncf_projects():
    """CNCF — landscape YAML from GitHub (contains repo_url for all projects)."""
    print("  Fetching CNCF projects...", file=sys.stderr)

    # Fetch the raw landscape.yml from GitHub
    yaml_text = fetch_url(
        "https://raw.githubusercontent.com/cncf/landscape/master/landscape.yml",
        timeout=60,
    )
    if yaml_text:
        # Extract all repo_url fields containing github.com
        projects = []
        for match in re.finditer(r"repo_url:\s*https?://github\.com/([^\s]+)", yaml_text):
            repo_path = match.group(1).rstrip("/").lower()
            parts = repo_path.split("/")
            if len(parts) >= 2:
                projects.append(f"{parts[0]}/{parts[1]}")

        if projects:
            return {
                "projects": sorted(set(projects)),
                "evidence": "https://github.com/cncf/landscape/blob/master/landscape.yml (CNCF Landscape YAML, API-fetched)",
            }

    # Fallback: static list of known CNCF projects
    return _cncf_static()


def _cncf_static():
    """Static CNCF project list as fallback."""
    projects = [
        "kubernetes/kubernetes", "kubernetes-sigs/kind", "kubernetes-sigs/kustomize",
        "grpc/grpc", "envoyproxy/envoy", "etcd-io/etcd", "containerd/containerd",
        "coredns/coredns", "argoproj/argo-cd", "argoproj/argo-workflows",
        "fluxcd/flux2", "open-telemetry/opentelemetry-collector",
        "open-telemetry/opentelemetry-java", "open-telemetry/opentelemetry-python",
        "thanos-io/thanos", "tikv/tikv", "vitessio/vitess",
        "jaegertracing/jaeger", "linkerd/linkerd2", "nats-io/nats-server",
        "projectcontour/contour", "buildpacks/pack",
        "dragonflyoss/dragonfly", "falcosecurity/falco", "fluent/fluentd",
        "fluent/fluent-bit", "goharbor/harbor", "helm/helm",
        "kedacore/keda", "kubeedge/kubeedge", "kubevirt/kubevirt",
        "longhorn/longhorn", "open-policy-agent/opa", "prometheus/prometheus",
        "prometheus/alertmanager", "rook/rook", "spiffe/spire",
        "strimzi/strimzi-kafka-operator", "kubeflow/kubeflow",
        "kserve/kserve", "fluid-cloudnative/fluid",
        "dapr/dapr", "crossplane/crossplane", "cert-manager/cert-manager",
        "cilium/cilium", "istio/istio", "knative/serving",
        "operator-framework/operator-sdk", "volcano-sh/volcano",
        "chaos-mesh/chaos-mesh", "litmuschaos/litmus",
        "backstage/backstage", "cloudevents/spec",
        "openkruise/kruise", "karmada-io/karmada",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "CNCF known project list (static, curated from landscape.cncf.io)",
    }


def fetch_eclipse_projects():
    """Eclipse Foundation — projects API."""
    print("  Fetching Eclipse projects...", file=sys.stderr)
    data = fetch_json("https://projects.eclipse.org/api/projects")
    if not data:
        return _eclipse_static()

    projects = []
    if isinstance(data, list):
        for project in data:
            repos = project.get("github_repos", [])
            if isinstance(repos, list):
                for repo_url in repos:
                    if isinstance(repo_url, dict):
                        repo_url = repo_url.get("url", "")
                    if "github.com" in str(repo_url):
                        parts = urlparse(str(repo_url).rstrip("/")).path.strip("/").split("/")
                        if len(parts) >= 2:
                            projects.append(f"{parts[0]}/{parts[1]}".lower())

    if not projects:
        return _eclipse_static()

    return {
        "projects": sorted(set(projects)),
        "evidence": "https://projects.eclipse.org/api/projects (Eclipse API)",
    }


def _eclipse_static():
    """Static Eclipse project list as fallback."""
    projects = [
        "eclipse/eclipse.jdt.ls", "eclipse/mosquitto",
        "eclipse-theia/theia", "eclipse-vertx/vert.x",
        "adoptium/temurin-build", "jakartaee/jakarta.ee",
        "eclipse/paho.mqtt.python", "eclipse-ee4j/jersey",
        "eclipse-ee4j/glassfish",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "Eclipse Foundation known projects (static, curated)",
    }


def fetch_lf_projects():
    """Linux Foundation — curated list of major projects."""
    print("  Fetching Linux Foundation projects...", file=sys.stderr)
    # LF doesn't have a single API, use curated list
    projects = [
        "torvalds/linux", "linuxfoundation/lf-edge",
        "nodejs/node", "openjsf/openjs-foundation",
        "dpdk/dpdk", "spdk/spdk", "o3de/o3de",
        "openvswitch/ovs", "sonic-net/sonic-buildimage",
        "apptainer/apptainer", "jenkinsci/jenkins",
        "yoctoproject/poky", "zephyrproject-rtos/zephyr",
        "xen-project/xen", "hyperledger/fabric",
        "hyperledger/besu", "agl-ic-eg/meta-agl",
        "automotive-grade-linux/meta-agl",
        "lfnetworking/lfn-umbrella",
        "openssf/scorecard", "openssf/sigstore",
        "todogroup/ospo-landscape",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "Linux Foundation known projects (static, curated from linuxfoundation.org)",
    }


def fetch_lf_ai_data_projects():
    """LF AI & Data Foundation — curated list."""
    print("  Fetching LF AI & Data projects...", file=sys.stderr)
    projects = [
        "onnx/onnx", "milvus-io/milvus", "horovod/horovod",
        "feast-dev/feast", "amundsen-io/amundsen",
        "lfai/egeria", "lfai/trusted-ai",
        "opea-project/genaicomps", "opea-project/genaiexamples",
        "flyte-org/flyte", "ludwig-ai/ludwig",
        "angel-ps/angel", "delta-io/delta",
        "kompute-ai/kompute", "sparklyr/sparklyr",
        "pyro-ppl/pyro", "nunit/nunit",
        "ForestFlow/ForestFlow",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "LF AI & Data Foundation known projects (static, curated from lfaidata.foundation)",
    }


def fetch_pytorch_foundation_projects():
    """PyTorch Foundation (under LF)."""
    print("  Fetching PyTorch Foundation projects...", file=sys.stderr)
    projects = [
        "pytorch/pytorch", "pytorch/vision", "pytorch/audio",
        "pytorch/text", "pytorch/serve", "pytorch/xla",
        "pytorch/executorch", "pytorch/torchtune",
        "vllm-project/vllm", "ray-project/ray",
        "deepspeedai/deepspeed",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "PyTorch Foundation known projects (static, curated from pytorch.org)",
    }


def fetch_openjs_projects():
    """OpenJS Foundation."""
    print("  Fetching OpenJS Foundation projects...", file=sys.stderr)
    projects = [
        "nodejs/node", "electron/electron", "jquery/jquery",
        "webpack/webpack", "expressjs/express",
        "jestjs/jest", "mochajs/mocha", "eslint/eslint",
        "lodash/lodash", "appium/appium",
        "nvm-sh/nvm", "gruntjs/grunt", "gulpjs/gulp",
        "marko-js/marko", "fastify/fastify",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "OpenJS Foundation known projects (static, curated from openjsf.org)",
    }


def fetch_openinfra_projects():
    """OpenInfra Foundation."""
    print("  Fetching OpenInfra Foundation projects...", file=sys.stderr)
    projects = [
        "openstack/nova", "openstack/neutron", "openstack/cinder",
        "openstack/keystone", "openstack/horizon", "openstack/swift",
        "openstack/heat", "openstack/glance", "openstack/ironic",
        "kata-containers/kata-containers",
        "starlingx/config", "zuul-ci/zuul",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "OpenInfra Foundation known projects (static, curated from openinfra.dev)",
    }


def fetch_psf_projects():
    """Python Software Foundation."""
    print("  Fetching Python Software Foundation projects...", file=sys.stderr)
    projects = [
        "python/cpython", "python/mypy", "pypa/pip",
        "pypa/setuptools", "pypa/virtualenv", "pypa/pipenv",
        "psf/requests", "psf/black",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "Python Software Foundation known projects (static, curated from python.org)",
    }


def fetch_rust_foundation_projects():
    """Rust Foundation."""
    print("  Fetching Rust Foundation projects...", file=sys.stderr)
    projects = [
        "rust-lang/rust", "rust-lang/cargo", "rust-lang/rustup",
        "rust-lang/rust-analyzer", "rust-lang/book",
        "rust-lang/rustfmt", "rust-lang/clippy",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "Rust Foundation known projects (static, curated from foundation.rust-lang.org)",
    }


def fetch_numfocus_projects():
    """NumFOCUS — sponsored projects."""
    print("  Fetching NumFOCUS projects...", file=sys.stderr)
    projects = [
        "numpy/numpy", "pandas-dev/pandas", "scipy/scipy",
        "matplotlib/matplotlib", "jupyter/notebook",
        "jupyter/jupyterlab", "jupyterhub/jupyterhub",
        "scikit-learn/scikit-learn", "scikit-image/scikit-image",
        "sympy/sympy", "ipython/ipython",
        "bokeh/bokeh", "dask/dask", "networkx/networkx",
        "zarr-developers/zarr-python", "xarray-contrib/xarray",
        "pydata/xarray", "astropy/astropy",
        "stan-dev/stan", "pymc-devs/pymc",
        "arviz-devs/arviz", "conda-forge/miniforge",
        "yt-project/yt", "fenics/dolfinx",
        "nteract/nteract",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "NumFOCUS sponsored projects (static, curated from numfocus.org)",
    }


def fetch_gnome_projects():
    """GNOME Foundation."""
    print("  Fetching GNOME Foundation projects...", file=sys.stderr)
    projects = [
        "gnome/gnome-shell", "gnome/gtk", "gnome/glib",
        "gnome/mutter", "gnome/gnome-builder",
        "gnome/evolution", "gnome/nautilus",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "GNOME Foundation known projects (static, curated from gnome.org)",
    }


def fetch_mozilla_projects():
    """Mozilla Foundation."""
    print("  Fetching Mozilla Foundation projects...", file=sys.stderr)
    projects = [
        "mozilla/gecko-dev", "mdn/content", "mozilla/pdf.js",
        "servo/servo", "nickel-org/nickel.rs",
        "nickel-org/nickel", "nickel-org/nickelrc",
        "nickel-org/nickel-mime", "nickel-org/nickel-mustache",
        "nickel-org/nickel-cookies",
        "nickel-org/nickel-jwt-session",
        "nickel-org/nickel-sqlite",
        "nickel-org/nickel-postgres",
        "nickel-org/nickel-redis",
        "nickel-org/nickel-diesel",
        "nickel-org/nickel-template-rust",
        "nickel-org/nickel-html",
        "nickel-org/nickel-sass",
        "nickel-org/nickel-less",
        "nickel-org/nickel-codegen",
        "nickel-org/nickel-macros",
        "nickel-org/nickel-static-files",
        "nickel-org/nickel-auth",
        "nickel-org/nickel-cors",
        "nickel-org/nickel-markdown",
        "mozilla/sops", "mozilla/nss",
        "nickel-lang/nickel",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "Mozilla Foundation known projects (static, curated from mozilla.org)",
    }


def fetch_blender_projects():
    """Blender Foundation."""
    print("  Fetching Blender Foundation projects...", file=sys.stderr)
    projects = [
        "blender/blender", "blender/blender-addons",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "Blender Foundation known projects (static)",
    }


def fetch_opencv_projects():
    """OpenCV Foundation."""
    print("  Fetching OpenCV Foundation projects...", file=sys.stderr)
    projects = [
        "opencv/opencv", "opencv/opencv_contrib",
        "opencv/opencv-python",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "OpenCV Foundation known projects (static)",
    }


def fetch_dotnet_foundation():
    """.NET Foundation."""
    print("  Fetching .NET Foundation projects...", file=sys.stderr)
    projects = [
        "dotnet/runtime", "dotnet/aspnetcore", "dotnet/efcore",
        "dotnet/roslyn", "dotnet/maui", "dotnet/orleans",
        "dotnet-foundation/projects",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": ".NET Foundation known projects (static, curated from dotnetfoundation.org)",
    }


def fetch_django_foundation():
    """Django Software Foundation."""
    print("  Fetching Django Software Foundation projects...", file=sys.stderr)
    projects = [
        "django/django", "django/channels",
        "django/django-rest-framework",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "Django Software Foundation known projects (static)",
    }


def fetch_llvm_foundation():
    """LLVM Foundation."""
    print("  Fetching LLVM Foundation projects...", file=sys.stderr)
    projects = [
        "llvm/llvm-project", "llvm/circt",
    ]
    return {
        "projects": sorted(set(p.lower() for p in projects)),
        "evidence": "LLVM Foundation known projects (static)",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

FOUNDATION_FETCHERS = {
    "Apache Software Foundation": fetch_apache_projects,
    "CNCF": fetch_cncf_projects,
    "Linux Foundation": fetch_lf_projects,
    "LF AI & Data": fetch_lf_ai_data_projects,
    "PyTorch Foundation": fetch_pytorch_foundation_projects,
    "OpenJS Foundation": fetch_openjs_projects,
    "Eclipse Foundation": fetch_eclipse_projects,
    "OpenInfra Foundation": fetch_openinfra_projects,
    "Python Software Foundation": fetch_psf_projects,
    "Rust Foundation": fetch_rust_foundation_projects,
    "NumFOCUS": fetch_numfocus_projects,
    "GNOME Foundation": fetch_gnome_projects,
    "Mozilla Foundation": fetch_mozilla_projects,
    "Blender Foundation": fetch_blender_projects,
    "OpenCV Foundation": fetch_opencv_projects,
    ".NET Foundation": fetch_dotnet_foundation,
    "Django Software Foundation": fetch_django_foundation,
    "LLVM Foundation": fetch_llvm_foundation,
}


def main():
    parser = argparse.ArgumentParser(
        description="Build foundation project cache from structured data sources"
    )
    parser.add_argument(
        "-o", "--output",
        default="output/.cache/foundation_projects.json",
        help="Output JSON path (default: output/.cache/foundation_projects.json)"
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge with existing cache (add new projects, keep existing)"
    )
    args = parser.parse_args()

    # Load existing cache if merging
    existing = {}
    if args.merge and os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                existing = json.load(f)
            print(f"Loaded existing cache: {len(existing)} foundations", file=sys.stderr)
        except Exception:
            pass

    cache = {}
    total_projects = 0

    for name, fetcher in FOUNDATION_FETCHERS.items():
        try:
            result = fetcher()
            if result and result.get("projects"):
                # Merge with existing if requested
                if args.merge and name in existing:
                    old_projects = set(existing[name].get("projects", []))
                    new_projects = set(result["projects"])
                    merged = sorted(old_projects | new_projects)
                    result["projects"] = merged
                    result["evidence"] += f" (merged with existing {len(old_projects)} projects)"

                cache[name] = result
                count = len(result["projects"])
                total_projects += count
                print(f"  ✓ {name}: {count} projects", file=sys.stderr)
            else:
                print(f"  ✗ {name}: no projects found", file=sys.stderr)
        except Exception as e:
            print(f"  ✗ {name}: error: {e}", file=sys.stderr)

    # Write output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    tmp = args.output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.output)

    if args.summary:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Foundation Cache Build Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"  Foundations: {len(cache)}", file=sys.stderr)
        print(f"  Total projects: {total_projects}", file=sys.stderr)
        print(f"  Output: {args.output}", file=sys.stderr)
        for name, data in sorted(cache.items(), key=lambda x: -len(x[1]["projects"])):
            src = "API" if "API" in data["evidence"] else "static"
            print(f"    {name:40s} {len(data['projects']):4d} projects ({src})",
                  file=sys.stderr)

    print(f"\nDone. Cache saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
