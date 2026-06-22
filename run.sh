
# 当任何命令执行失败时，立即退出脚本
set -e

# 获取脚本所在的目录，并切换到该目录
# 这使得脚本可以从任何位置被调用
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

export NFOFETCH_BROWSE_ROOT=/home/syaofox/Videos
export NFOFETCH_JAVDB_COOKIE='_jdb_session=zQ%2Fk53jNHZsYydQvZLw1aaz3ArBcRvHlq%2BmY9kwaEd8UbFPO6F1TLdmfMDhVWlytUTbRnSg4wyoglyDqphprP27YPs9Kn43KBTRJcotsbjmFvgIabmGXwUdJ6n6jAxmTt0lDUgBVpQR2qvbw1ZT3DFz80DOFXWPQUWCYp7eOED1TpcB5pNhq4ZMHg5qROz6Dee%2Fdp9%2FoiH1SJKfdUMtbBndfWVvER%2FMWIz9XnRYWhWfzLROROGZSgwsPiBwxLT5EqjnX%2BUfj35gAYibAESZ9kBCDTwjNPErJB8NcnlVCJWQLnk2fQJPl8Q7cFbGwr7JkngEtUSUkGAYIzLAGTOeNl3VC6dIJPBrpW7df4sSR5GfVk%2FuLdysWPx3kAUIJuKHo4Qg%3D--%2B5sbscBwlc4%2F1ccx--SFjAKOYscVwjgl5zEZQTMw%3D%3D; path=/; expires=Tue, 07 Jul 2026 06:57:13 GMT; secure; HttpOnly; SameSite=None'
export NFOFETCH_LOG_LEVEL=INFO
export NFOFETCH_SERIAL_WRITES=true

uv run uvicorn app.main:app --reload
