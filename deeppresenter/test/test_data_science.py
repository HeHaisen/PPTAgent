"""Test data science pipeline: numpy + pandas + matplotlib + seaborn."""

import pytest

PIPELINE_SCRIPT = """\
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

np.random.seed(42)
data = pd.DataFrame({
    '日期': pd.date_range('2024-01-01', periods=100),
    '数值': np.random.randn(100).cumsum(),
    '类别': np.random.choice(['产品A', '产品B', '产品C'], 100),
    '销量': np.random.randint(10, 100, 100)
})
data.to_csv('原始数据.csv', index=False, encoding='utf-8')

fig, axes = plt.subplots(2, 2, figsize=(14, 12))
axes[0, 0].plot(data['日期'], data['数值'], linewidth=2, color='steelblue')
axes[0, 0].set_title('时间序列趋势图', fontsize=14, fontweight='bold')
axes[0, 1].hist(data['数值'], bins=20, edgecolor='black', alpha=0.7, color='coral')
axes[0, 1].set_title('数值分布直方图', fontsize=14, fontweight='bold')
sns.boxplot(data=data, x='类别', y='销量', ax=axes[1, 0], palette='Set2')
axes[1, 0].set_title('各产品销量箱线图', fontsize=14, fontweight='bold')
for cat in data['类别'].unique():
    cat_data = data[data['类别'] == cat]
    axes[1, 1].scatter(cat_data.index, cat_data['数值'], label=cat, alpha=0.6, s=50)
axes[1, 1].set_title('散点分布图', fontsize=14, fontweight='bold')
axes[1, 1].legend()
plt.tight_layout()
plt.savefig('数据可视化报告.png', dpi=100, bbox_inches='tight')
print('SUCCESS')
"""


@pytest.mark.asyncio
async def test_data_visualization_pipeline(agent_env, workspace, tool_call_helper):
    """Test complete data science pipeline with Chinese labels."""
    write_call = tool_call_helper(
        "write_file",
        {"path": str(workspace / "pipeline.py"), "content": PIPELINE_SCRIPT},
    )
    await agent_env.tool_execute(write_call)

    exec_call = tool_call_helper(
        "execute_command", {"command": f"python {workspace / 'pipeline.py'}"}
    )
    result = await agent_env.tool_execute(exec_call)
    assert not result.is_error and "SUCCESS" in result.text

    list_call = tool_call_helper("list_directory", {"path": str(workspace)})
    list_result = await agent_env.tool_execute(list_call)
    assert "原始数据.csv" in list_result.text
    assert "数据可视化报告.png" in list_result.text
