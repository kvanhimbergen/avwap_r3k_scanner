export interface ApiEnvelope<T> {
  as_of_utc: string;
  source_window: {
    date_min: string | null;
    date_max: string | null;
    [key: string]: unknown;
  };
  data_version: string;
  warnings: string[];
  data: T;
}

export interface KeyValue {
  [key: string]: unknown;
}

export interface TimePoint {
  ny_date: string;
  cycle_count: number;
  intent_count: number;
  created_count: number;
  accepted_count: number;
  rejected_count: number;
  gate_blocks: number;
}

export interface FreshnessRow {
  source_name: string;
  source_glob: string;
  file_count: number;
  row_count: number;
  latest_mtime_utc: string | null;
  parse_status: string;
  last_error: string | null;
}
