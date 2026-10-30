const DIMENSION_LABELS: Record<string, string> = {
  production_line: "产线（Production Line）",
  vehicle_model: "车型（Vehicle Model）",
  workstation: "工位（Workstation）",
  shift: "班次（Shift）",
  supplier_id: "供应商（Supplier）",
  batch_id: "批次（Batch）",
  defect_type: "缺陷类型（Defect Type）",
};

const VALUE_LABELS: Record<string, Record<string, string>> = {
  shift: {
    day: "白班（Day）",
    night: "夜班（Night）",
  },
  defect_type: {
    torque_low: "扭矩偏低（Torque Low）",
    torque_high: "扭矩偏高（Torque High）",
    pressure_low: "压力偏低（Pressure Low）",
    pressure_high: "压力过高（Pressure High）",
    temperature_drift: "温度漂移（Temperature Drift）",
    weld_pore: "焊接气孔（Weld Porosity）",
    seal_leak: "密封泄漏（Seal Leak）",
    electrical_open: "电路开路（Electrical Open）",
  },
};

export function qualityDimensionLabel(value: unknown): string {
  const raw = String(value ?? "因素").trim();
  return DIMENSION_LABELS[raw.toLowerCase()] ?? raw;
}

export function qualityValueLabel(dimension: unknown, value: unknown): string {
  const raw = String(value ?? "").trim();
  const labels = VALUE_LABELS[String(dimension ?? "").toLowerCase()];
  return labels?.[raw.toLowerCase()] ?? raw;
}
