// my_data.js - 我的数据仪表盘视图

function myDataMixin() {
    return {
        // ===== 我的数据状态 =====
        myStats: null,
        statsLoading: false,

        async loadMyStats() {
            this.statsLoading = true;
            try {
                this.myStats = await this.api('/api/my-stats');
            } catch (e) {
                this.showToast('加载数据失败', e.message, 'error');
            } finally {
                this.statsLoading = false;
            }
        },

        // 月度柱状图高度计算（百分比归一化）
        monthBarHeight(count, allMonthly) {
            const max = Math.max(...Object.values(allMonthly), 1);
            return Math.round((count / max) * 100);
        },

        // 月份标签：每年第一个月显示年份，否则只显示月份
        formatMonthLabel(month) {
            if (!month) return '';
            const [year, mon] = month.split('-');
            // 找出全部月份数据中的第一个月，显示年份
            const all = Object.keys(this.myStats?.monthly?.created || {});
            const isFirstOfYear = all.filter(m => m.endsWith('-' + mon)).indexOf(month) === 0;
            // 仅当是这一年的第一个月时显示年份
            const sameYearMonths = all.filter(m => m.startsWith(year + '-'));
            if (sameYearMonths[0] === month) {
                return year.slice(2) + '/' + mon;
            }
            return mon;
        },
    };
}
