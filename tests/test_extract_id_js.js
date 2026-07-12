/**
 * nfExtractId JavaScript 提取逻辑测试
 * 运行: node tests/test_extract_id_js.js
 *
 * 验证从路径中自动提取番号的逻辑是否正确。
 * 与 app/templates/base.html 中 window.nfExtractId 的提取逻辑保持一致。
 */

// 从 base.html 中提取的核心逻辑（不含 DOM 操作）
function extractIds(path) {
  var ids = [];
  var sourceText = path;
  var cleanedText = sourceText;

  var m;
  // HEYZO 番号：HEYZO-0282（固定4位，保留前导零）
  var reHeyzo = /(HEYZO)[-_]?(\d{4})/gi;
  cleanedText = cleanedText.replace(/HEYZO[-_]?\d{4}/gi, "");
  while ((m = reHeyzo.exec(sourceText)) !== null) {
    ids.push(m[1].toUpperCase() + "-" + m[2]);
  }
  // PT 番号：PT-12（可变位数，不补0）
  var rePT = /(PT)[-_]?(\d+)/gi;
  cleanedText = cleanedText.replace(/PT[-_]?\d+/gi, "");
  while ((m = rePT.exec(sourceText)) !== null) {
    ids.push(m[1].toUpperCase() + "-" + m[2]);
  }
  // 标准番号：ABC-123 / ABC_123（对 cleanedText 匹配）
  var reStd = /([A-Za-z]{2,6})[-_]?(\d{2,8})/g;
  while ((m = reStd.exec(cleanedText)) !== null) {
    ids.push(m[1].toUpperCase() + "-" + String(parseInt(m[2], 10)).padStart(3, "0"));
  }
  // 纯数字番号：101413-455（连字符版）
  var reNumH = /(\d{4,})\s*-\s*(\d{2,6})/g;
  while ((m = reNumH.exec(sourceText)) !== null) {
    ids.push(m[1] + "-" + m[2]);
  }
  // 纯数字番号：101413_455（下划线版）
  var reNumU = /(\d{4,})\s*_\s*(\d{2,6})/g;
  while ((m = reNumU.exec(sourceText)) !== null) {
    ids.push(m[1] + "_" + m[2]);
  }
  // n 前缀番号：n0179 / N0179
  var reN = /n(\d{2,8})/gi;
  while ((m = reN.exec(sourceText)) !== null) {
    ids.push("N" + m[1]);
  }
  // 去重
  ids = ids.filter(function (v, i) { return ids.indexOf(v) === i; });
  return ids;
}

// ===== 测试用例 =====
var tests = [
  // --- 标准番号 ---
  { path: "/mnt/videos/ABC-123.mp4", expected: ["ABC-123"], desc: "标准番号 hyphen" },
  { path: "/mnt/videos/ABC_123.mp4", expected: ["ABC-123"], desc: "标准番号 underscore" },
  { path: "/mnt/videos/ABC123.mp4", expected: ["ABC-123"], desc: "标准番号 无分隔符" },
  { path: "/mnt/videos/abc-123.mp4", expected: ["ABC-123"], desc: "标准番号 小写" },
  { path: "/mnt/videos/IPVR-335.mp4", expected: ["IPVR-335"], desc: "IPVR 格式" },
  { path: "/mnt/videos/AB-12.mp4", expected: ["AB-012"], desc: "短数字补零" },
  { path: "/mnt/videos/ABC-1.mp4", expected: [], desc: "数字过短 不匹配" },

  // --- HEYZO ---
  { path: "/mnt/videos/HEYZO-0282.mp4", expected: ["HEYZO-0282"], desc: "HEYZO 固定4位" },
  { path: "/mnt/videos/heyzo_0282.mp4", expected: ["HEYZO-0282"], desc: "HEYZO 下划线" },
  { path: "/mnt/videos/HEYZO0282.mp4", expected: ["HEYZO-0282"], desc: "HEYZO 无分隔符" },

  // --- PT ---
  { path: "/mnt/videos/PT-12.mp4", expected: ["PT-12"], desc: "PT 可变位数" },
  { path: "/mnt/videos/PT-123.mp4", expected: ["PT-123"], desc: "PT 3位数" },

  // --- N 前缀 ---
  { path: "/mnt/videos/N0179.mp4", expected: ["N0179"], desc: "N 前缀 大写" },
  { path: "/mnt/videos/n0179.mp4", expected: ["N0179"], desc: "N 前缀 小写" },

  // --- 纯数字番号 ---
  { path: "/mnt/videos/101413-455.mp4", expected: ["101413-455"], desc: "纯数字 hyphen" },
  { path: "/mnt/videos/101413_455.mp4", expected: ["101413_455"], desc: "纯数字 underscore" },

  // --- 无匹配 ---
  { path: "/mnt/videos/no-match.mp4", expected: [], desc: "无番号文件名" },
  { path: "/mnt/videos/123.mp4", expected: [], desc: "纯短数字" },

  // --- 多匹配 ---
  { path: "/mnt/videos/ABC-123-XYZ-456.mp4", expected: ["ABC-123", "XYZ-456"], desc: "多番号 同文件名" },
  { path: "/mnt/videos/ABC-123/DEF-456.mp4", expected: ["ABC-123", "DEF-456"], desc: "多番号 目录+文件" },
  { path: "/mnt/videos/ABC-123+GHI-789.mp4", expected: ["ABC-123", "GHI-789"], desc: "多番号 不同分隔" },

  // --- 边缘路径 ---
  { path: "/mnt/videos/VIDEO-2024/ABC-123.mp4", expected: ["VIDEO-2024", "ABC-123"], desc: "目录含类似番号" },
  { path: "/mnt/videos/A&B/ABC-123.mp4", expected: ["ABC-123"], desc: "路径含 &" },
  { path: "/mnt/my videos/ABC-123.mp4", expected: ["ABC-123"], desc: "路径含空格" },
  { path: "/mnt/videos/ABC-123 (1984).mp4", expected: ["ABC-123"], desc: "文件名含括号" },
  { path: "/mnt/videos/ABC-123.1080p.mp4", expected: ["ABC-123"], desc: "文件名含分辨率" },
  { path: "/mnt/videos/2024/ABC-123.mp4", expected: ["ABC-123"], desc: "年份目录" },
  { path: "/mnt/videos/MiMa-123.mp4", expected: ["MIMA-123"], desc: "混合大小写" },
  { path: "/mnt/user/data/videos/subdir/ABC-123.mp4", expected: ["ABC-123"], desc: "长路径" },
];

// ===== 运行测试 =====
var passed = 0;
var failed = 0;
tests.forEach(function (t) {
  var result = extractIds(t.path);
  var resultStr = JSON.stringify(result);
  var expectedStr = JSON.stringify(t.expected);
  if (resultStr === expectedStr) {
    console.log("  PASS: " + t.desc);
    passed++;
  } else {
    console.log("  FAIL: " + t.desc);
    console.log("        path: " + t.path);
    console.log("        got: " + resultStr + "  expected: " + expectedStr);
    failed++;
  }
});

console.log("\n================================");
console.log("结果: " + passed + " passed, " + failed + " failed, " + (passed + failed) + " total");
if (failed > 0) {
  process.exit(1);
}
