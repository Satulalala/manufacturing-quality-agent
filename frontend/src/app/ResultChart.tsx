import { useEffect, useRef } from "react";
import { init, use } from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { qualityDimensionLabel, qualityValueLabel } from "./qualityLabels";
import type { QualityParetoItem, QualityTrendPoint } from "./types";

use([BarChart, LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, CanvasRenderer]);

export function ResultChart({ factors }: { factors: Array<Record<string, unknown>> }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!hostRef.current || factors.length === 0) return;
    const chart = init(hostRef.current);
    const chartFactors = factors.slice(0, 7);
    const hasBatchFactor = chartFactors.some((factor) => factor.dimension === "batch_id");
    const categories = chartFactors.map((factor) => factor.dimension === "batch_id"
      ? qualityValueLabel(factor.dimension, factor.value)
      : `${qualityDimensionLabel(factor.dimension)} · ${qualityValueLabel(factor.dimension, factor.value)}`);
    const values = chartFactors.map((factor) => {
      const percent = Number(factor.defect_rate_percent ?? (Number(factor.defect_rate) * 100));
      return Number.isFinite(percent) ? Number(percent.toFixed(2)) : Number(factor.priority_score ?? 0);
    });
    chart.setOption({
      animation: false,
      grid: { left: hasBatchFactor ? 170 : 112, right: 18, top: 10, bottom: 24 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (value: unknown) => `${value}%` },
      xAxis: { type: "value", axisLabel: { color: "#7b8492", fontSize: 11, formatter: "{value}%" }, splitLine: { lineStyle: { color: "#edf0f3" } } },
      yAxis: { type: "category", data: categories, inverse: true, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: "#455061", fontSize: 12, width: hasBatchFactor ? 158 : 102, overflow: "truncate" } },
      series: [{ type: "bar", data: values, barWidth: 16, itemStyle: { color: "#5475c7", borderRadius: [0, 4, 4, 0] }, label: { show: true, position: "right", color: "#526076", fontSize: 11, formatter: "{c}%" } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [factors]);

  return <div ref={hostRef} className="factor-chart" role="img" aria-label="候选因素不良率对比图" />;
}

export function TrendChart({ points }: { points: QualityTrendPoint[] }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!hostRef.current || points.length === 0) return;
    const chart = init(hostRef.current);
    chart.setOption({
      animation: false,
      grid: { left: 48, right: 18, top: 18, bottom: 42 },
      tooltip: { trigger: "axis", valueFormatter: (value: unknown) => `${Number(value).toFixed(2)}%` },
      xAxis: {
        type: "category",
        data: points.map((point) => point.period),
        boundaryGap: false,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#d8dee8" } },
        axisLabel: { color: "#778397", fontSize: 11, hideOverlap: true, rotate: points.length > 14 ? 25 : 0 },
      },
      yAxis: {
        type: "value",
        min: 0,
        name: "不良率",
        nameTextStyle: { color: "#778397", fontSize: 11 },
        axisLabel: { color: "#778397", fontSize: 11, formatter: "{value}%" },
        splitLine: { lineStyle: { color: "#edf0f3" } },
      },
      series: [{
        name: "不良率",
        type: "line",
        data: points.map((point) => Number(point.defect_rate_percent.toFixed(2))),
        smooth: false,
        showSymbol: points.length <= 45,
        symbolSize: 5,
        lineStyle: { color: "#4567b2", width: 2 },
        itemStyle: { color: "#4567b2" },
        areaStyle: { color: "rgba(69, 103, 178, 0.10)" },
      }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [points]);

  return <div ref={hostRef} className="trend-chart" role="img" aria-label="按日期变化的不良率趋势图" />;
}

export function ParetoChart({ items }: { items: QualityParetoItem[] }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!hostRef.current || items.length === 0) return;
    const chart = init(hostRef.current);
    chart.setOption({
      animation: false,
      grid: { left: 48, right: 54, top: 42, bottom: 52 },
      legend: { top: 4, textStyle: { color: "#68758a", fontSize: 11 } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        type: "category",
        data: items.map((item) => qualityValueLabel("defect_type", item.defect_type)),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#d8dee8" } },
        axisLabel: { color: "#68758a", fontSize: 10, interval: 0, rotate: items.length > 4 ? 20 : 0 },
      },
      yAxis: [
        { type: "value", name: "缺陷数", min: 0, axisLabel: { color: "#778397", fontSize: 10 }, splitLine: { lineStyle: { color: "#edf0f3" } } },
        { type: "value", name: "累计占比", min: 0, max: 100, axisLabel: { color: "#778397", fontSize: 10, formatter: "{value}%" }, splitLine: { show: false } },
      ],
      series: [
        {
          name: "缺陷数",
          type: "bar",
          data: items.map((item) => item.count),
          barMaxWidth: 30,
          itemStyle: { color: "#5475c7", borderRadius: [4, 4, 0, 0] },
        },
        {
          name: "累计占比",
          type: "line",
          yAxisIndex: 1,
          data: items.map((item) => Number(item.cumulative_percent.toFixed(2))),
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { color: "#c46a52", width: 2 },
          itemStyle: { color: "#c46a52" },
          markLine: {
            symbol: "none",
            label: { formatter: "80%", color: "#a97636" },
            lineStyle: { color: "#c39a5e", type: "dashed" },
            data: [{ yAxis: 80 }],
          },
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [items]);

  return <div ref={hostRef} className="pareto-chart" role="img" aria-label="按缺陷类型排序并显示累计占比的 Pareto 图" />;
}

