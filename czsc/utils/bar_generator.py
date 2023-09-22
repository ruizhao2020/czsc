# -*- coding: utf-8 -*-
"""
author: zengbin93
email: zeng_bin8888@163.com
create_dt: 2021/11/14 12:39
describe: 从任意周期K线开始合成更高周期K线的工具类
"""
import pandas as pd
from datetime import datetime, timedelta, date
from typing import List, Union, AnyStr
from czsc.objects import RawBar, Freq
from pathlib import Path
from loguru import logger
from czsc.utils.calendar import next_trading_date


mss = pd.read_feather(Path(__file__).parent / "minites_split.feather")
freq_market_times, freq_edt_map = {}, {}
for _m, dfg in mss.groupby('market'):
    for _f in [x for x in mss.columns if x.endswith("分钟")]:
        freq_market_times[f"{_f}_{_m}"] = list(dfg[_f].unique())
        freq_edt_map[f"{_f}_{_m}"] = {k: v for k, v in dfg[["time", _f]].values}


def check_freq_and_market(time_seq: List[AnyStr]):
    """检查时间序列是否为同一周期，是否为同一市场

    :param time_seq: 时间序列，如 ['11:00', '15:00', '23:00', '01:00', '02:30']
    :return:
        - freq      K线周期
        - market    交易市场
    """
    assert len(time_seq) >= 2, "time_seq长度必须大于等于2"
    res = {}
    for key, tts in freq_market_times.items():
        if set(tts) == set(time_seq):
            freq, market = key.split("_")
            return freq, market

        if len(time_seq) < len(tts) * 0.9 or len(time_seq) > len(tts) * 1.1:
            continue

        res[key] = len(set(time_seq).intersection(set(tts))) / len(tts)
    freq, market = sorted(res.items(), key=lambda x: x[1], reverse=True)[0][0].split("_")
    return freq, market


def freq_end_date(dt, freq: Union[Freq, AnyStr]):
    """交易日结束时间计算"""
    if not isinstance(dt, date):
        dt = pd.to_datetime(dt).date()
    if not isinstance(freq, Freq):
        freq = Freq(freq)

    dt = pd.to_datetime(dt)
    if freq == Freq.D:
        return dt

    if freq == Freq.W:
        return dt + timedelta(days=5 - dt.isoweekday())

    if freq == Freq.Y:
        return datetime(year=dt.year, month=12, day=31)

    if freq == Freq.M:
        if dt.month == 12:
            edt = datetime(year=dt.year, month=12, day=31)
        else:
            edt = datetime(year=dt.year, month=dt.month + 1, day=1) - timedelta(days=1)
        return edt

    if freq == Freq.S:
        dt_m = dt.month
        if dt_m in [1, 2, 3]:
            edt = datetime(year=dt.year, month=4, day=1) - timedelta(days=1)
        elif dt_m in [4, 5, 6]:
            edt = datetime(year=dt.year, month=7, day=1) - timedelta(days=1)
        elif dt_m in [7, 8, 9]:
            edt = datetime(year=dt.year, month=10, day=1) - timedelta(days=1)
        else:
            edt = datetime(year=dt.year, month=12, day=31)
        return edt

    logger.warning(f'error: {dt} - {freq}')
    return dt


def freq_end_time_V230921(dt: datetime, freq: Union[Freq, AnyStr], market="A股") -> datetime:
    """A股与期货市场精确的获取 dt 对应的K线周期结束时间

    :param dt: datetime
    :param freq: Freq
    :return: datetime
    """
    assert market in ['A股', '期货', '默认'], "market 参数必须为 A股 或 期货 或 默认"
    if not isinstance(freq, Freq):
        freq = Freq(freq)
    if dt.second > 0 or dt.microsecond > 0:
        dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)

    hm = dt.strftime("%H:%M")
    key = f"{freq.value}_{market}"
    if freq.value.endswith("分钟"):
        h, m = freq_edt_map[key][hm].split(":")
        edt = dt.replace(hour=int(h), minute=int(m))
        return edt

    if not ("15:00" > hm > "09:00") and market == "期货":
        dt = next_trading_date(dt.strftime("%Y-%m-%d"), 1)

    return freq_end_date(dt.date(), freq)


def freq_end_time(dt: datetime, freq: Union[Freq, AnyStr]) -> datetime:
    """获取 dt 对应的K线周期结束时间

    :param dt: datetime
    :param freq: Freq
    :return: datetime
    """
    if not isinstance(freq, Freq):
        freq = Freq(freq)
    dt = dt.replace(second=0, microsecond=0)

    if freq in [Freq.F1, Freq.F5, Freq.F15, Freq.F30, Freq.F60]:
        m = int(str(freq.value).strip("分钟"))
        if m < 60:
            if (dt.hour == 15 and dt.minute == 0) or (dt.hour == 11 and dt.minute == 30):
                return dt

            delta_m = dt.minute % m
            if delta_m != 0:
                dt += timedelta(minutes=m - delta_m)
            return dt

        else:
            dt_span = {
                60: ["01:00", "2:00", "3:00", '10:30', "11:30", "14:00", "15:00", "22:00", "23:00", "23:59"],
            }
            for v in dt_span[m]:
                hour, minute = v.split(":")
                edt = dt.replace(hour=int(hour), minute=int(minute))
                if dt <= edt:
                    return edt

    # 处理 日、周、月、季、年 的结束时间
    return freq_end_date(dt.date(), freq)


def resample_bars(df: pd.DataFrame, target_freq: Union[Freq, AnyStr], raw_bars=True, **kwargs):
    """将df中的K线序列转换为目标周期的K线序列

    :param df: 原始K线数据，必须包含以下列：symbol, dt, open, close, high, low, vol, amount。样例如下：
               symbol                  dt     open    close     high      low  \
        0  000001.XSHG 2015-01-05 09:31:00  3258.63  3259.69  3262.85  3258.63
        1  000001.XSHG 2015-01-05 09:32:00  3258.33  3256.19  3259.55  3256.19
        2  000001.XSHG 2015-01-05 09:33:00  3256.10  3257.50  3258.42  3256.10
        3  000001.XSHG 2015-01-05 09:34:00  3259.33  3261.76  3261.76  3257.98
        4  000001.XSHG 2015-01-05 09:35:00  3261.71  3264.88  3265.48  3261.71
                  vol        amount
        0  1333523100  4.346872e+12
        1   511386100  1.665170e+12
        2   455375200  1.483385e+12
        3   363393800  1.185303e+12
        4   402854600  1.315272e+12
    :param target_freq: 目标周期
    :param raw_bars: 是否将转换后的K线序列转换为RawBar对象
    :return: 转换后的K线序列
    """
    if not isinstance(target_freq, Freq):
        target_freq = Freq(target_freq)

    market = kwargs.get("market", "默认")
    df['freq_edt'] = df['dt'].apply(lambda x: freq_end_time_V230921(x, target_freq, market))
    dfk1 = df.groupby('freq_edt').agg(
        {'symbol': 'first', 'dt': 'last', 'open': 'first', 'close': 'last', 'high': 'max',
         'low': 'min', 'vol': 'sum', 'amount': 'sum', 'freq_edt': 'last'})
    dfk1.reset_index(drop=True, inplace=True)
    dfk1['dt'] = dfk1['freq_edt']
    dfk1 = dfk1[['symbol', 'dt', 'open', 'close', 'high', 'low', 'vol', 'amount']]

    if raw_bars:
        _bars = []
        for i, row in enumerate(dfk1.to_dict("records"), 1):
            row.update({'id': i, 'freq': target_freq})
            _bars.append(RawBar(**row))

        if df['dt'].iloc[-1] < _bars[-1].dt:
            # 清除最后一根未完成的K线
            _bars.pop()

        return _bars
    else:
        return dfk1


class BarGenerator:

    def __init__(self, base_freq: str, freqs: List[str], max_count: int = 5000):
        self.symbol = None
        self.end_dt = None
        self.base_freq = base_freq
        self.max_count = max_count
        self.freqs = freqs
        self.bars = {v: [] for v in self.freqs}
        self.bars.update({base_freq: []})
        self.freq_map = {f.value: f for _, f in Freq.__members__.items()}
        self.__validate_freqs()

    def __validate_freqs(self):
        sorted_freqs = ['Tick', '1分钟', '5分钟', '15分钟', '30分钟', '60分钟', '日线', '周线', '月线', '季线', '年线']
        i = sorted_freqs.index(self.base_freq)
        f = sorted_freqs[i:]
        for freq in self.freqs:
            if freq not in f:
                raise ValueError(f'freqs中包含不支持的周期：{freq}')

    def init_freq_bars(self, freq: str, bars: List[RawBar]):
        """初始化某个周期的K线序列

        :param freq: 周期名称
        :param bars: K线序列
        :return:
        """
        assert freq in self.bars.keys()
        assert not self.bars[freq], f"self.bars['{freq}'] 不为空，不允许执行初始化"
        self.bars[freq] = bars
        self.symbol = bars[-1].symbol

    def __repr__(self):
        return f"<BarGenerator for {self.symbol} @ {self.end_dt}>"

    def _update_freq(self, bar: RawBar, freq: Freq) -> None:
        """更新指定周期K线

        :param bar: 基础周期已完成K线
        :param freq: 目标周期
        :return:
        """
        freq_edt = freq_end_time(bar.dt, freq)

        if not self.bars[freq.value]:
            bar_ = RawBar(symbol=bar.symbol, freq=freq, dt=freq_edt, id=0, open=bar.open,
                          close=bar.close, high=bar.high, low=bar.low, vol=bar.vol, amount=bar.amount)
            self.bars[freq.value].append(bar_)
            return

        last: RawBar = self.bars[freq.value][-1]
        if freq_edt != self.bars[freq.value][-1].dt:
            bar_ = RawBar(symbol=bar.symbol, freq=freq, dt=freq_edt, id=last.id + 1, open=bar.open,
                          close=bar.close, high=bar.high, low=bar.low, vol=bar.vol, amount=bar.amount)
            self.bars[freq.value].append(bar_)

        else:
            bar_ = RawBar(symbol=bar.symbol, freq=freq, dt=freq_edt, id=last.id,
                          open=last.open, close=bar.close, high=max(last.high, bar.high),
                          low=min(last.low, bar.low), vol=last.vol + bar.vol, amount=last.amount + bar.amount)
            self.bars[freq.value][-1] = bar_

    def update(self, bar: RawBar) -> None:
        """更新各周期K线

        :param bar: 必须是已经结束的Bar
        :return:
        """
        base_freq = self.base_freq
        assert bar.freq.value == base_freq
        self.symbol = bar.symbol
        self.end_dt = bar.dt

        if self.bars[base_freq] and self.bars[base_freq][-1].dt == bar.dt:
            print(f"BarGenerator.update: 输入重复K线，基准周期为{base_freq}")
            return

        for freq in self.bars.keys():
            self._update_freq(bar, self.freq_map[freq])

        # 限制存在内存中的K限制数量
        for f, b in self.bars.items():
            self.bars[f] = b[-self.max_count:]
