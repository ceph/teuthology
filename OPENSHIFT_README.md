# OpenShift VM Provisioning - Documentation

## 📚 Main Documentation

**👉 See [`OPENSHIFT_GUIDE.md`](OPENSHIFT_GUIDE.md) for complete documentation**

This single comprehensive guide contains:
- ✅ Quick Start (5 minutes)
- ✅ Prerequisites & Installation
- ✅ Configuration (basic & advanced)
- ✅ Usage Instructions
- ✅ How It Works (internals)
- ✅ Troubleshooting
- ✅ Complete Reference

## 📁 Additional Files

- **Example Config:** [`examples/openshift_teuthology_config.yaml`](examples/openshift_teuthology_config.yaml)
- **Implementation:** `teuthology/provision/cloud/openshift.py` (746 lines)
- **Tests:** `teuthology/provision/cloud/test/test_openshift.py` (8 tests)
- **User Docs:** `docs/openshift_backend.rst` (for Sphinx docs)

## 🚀 Quick Start

```bash
# 1. Install
pip install -e '.[openshift]'

# 2. Configure ~/.teuthology.yaml
# (see OPENSHIFT_GUIDE.md or examples/openshift_teuthology_config.yaml)

# 3. Use it!
teuthology-lock --lock --machine-type openshift-vms --num 3
```

---

**Start here: [`OPENSHIFT_GUIDE.md`](OPENSHIFT_GUIDE.md)** 📖

