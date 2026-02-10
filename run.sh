
# 当任何命令执行失败时，立即退出脚本
set -e

# 获取脚本所在的目录，并切换到该目录
# 这使得脚本可以从任何位置被调用
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

export NFOFETCH_BROWSE_ROOT=/mnt/dnas
export NFOFETCH_JAVDB_COOKIE='theme=auto; locale=zh; over18=1; list_mode=v; _rucaptcha_session_id=3af5fd54faa2083dafab2be9e05c510a; _jdb_session=hUyIzRwy427H%2FIICpZqH6wxjw4skvyk%2F14ws4mlJmpm9Y6ZMe6VxUA%2FBI2xJm4ULiI0pHudwu1wGg8ltsN6Wd6Aio15Sk56A2kP1j3YAVOznVgbxTlyBVUWUBhohStSjOchFm48H2qS%2FckoOviznJzVRysNsPLc6%2FpXlhdhcTfm7v1SXSHc0GhtclYweBlWTz2GEe9JN7%2BzoZtvwVtKg4ieAFN8aDUshvV6DVQ7ocNWFPeDfnb29j8WMSJ%2B9Qb9tmDCP%2Fkw08x8dM%2F6r%2Bv4OKmz8X9R1hqG0ZbqgUFqBAg5rA6ZJOmFC15%2B%2FdDLs6zhKbreY%2FGGBViqm%2BA4HiQWIAywzy081rQZqkO0uUj8QO%2FVy5klwochA2BPOUO4ijqK43AE%3D--pqKcAI0w4%2BMtXat5--CnBEv3gxgc2uBiuLOrkxXw%3D%3D; cf_clearance=gm5n2F69ID_VKbdc4H3VyNmgBPLxBX1m_tRqRd87PX8-1770692071-1.2.1.1-WZHHO0qXcQ3VQefxqPOqXl88oJWhr2ioEPuo0CpBjqteqeD19rXAw16x35zt1oLEn5S2VKk.GC.UsNsSaXeN_G_ox9sbIaEPPGhogsZYaXJfZ5j9tiQWuEvNU82bn4ARA2NA4_lb7x0DhmxHY.JoCAaDhuh.56RAM4wRhC42mXZx4EZeU9MCTsBtUk94er5zmZG9Fqt7YuIXSVe211rXJL_NSbbnw3m_DxmYVUdQfBU'


uv run uvicorn app.main:app --reload
