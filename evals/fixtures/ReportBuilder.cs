// Nightly meter-reading roll-up.
// Reads the raw meter CSV, throws away readings the loggers marked as suspect,
// and writes one average per site for the morning dashboard.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;

namespace Metering.Reporting
{
    public sealed class MeterRow
    {
        public string Site { get; set; }
        public string Flag { get; set; }
        public string Value { get; set; }
    }

    public static class ReportBuilder
    {
        private static readonly HashSet<string> SuspectFlags =
            new HashSet<string> { "E", "X", "?" };

        public static List<MeterRow> LoadRows(string path)
        {
            return File.ReadAllLines(path)
                .Skip(1)
                .Select(line => line.Split(','))
                .Select(parts => new MeterRow { Site = parts[0], Flag = parts[1], Value = parts[2] })
                .ToList();
        }

        public static bool IsUsable(MeterRow row)
        {
            return !SuspectFlags.Contains(row.Flag) && !string.IsNullOrEmpty(row.Value);
        }

        public static Dictionary<string, double> SiteAverages(IEnumerable<MeterRow> rows)
        {
            var totals = new Dictionary<string, double>();
            var seen = new Dictionary<string, int>();

            foreach (var row in rows)
            {
                seen.TryGetValue(row.Site, out var count);
                seen[row.Site] = count + 1;

                if (!IsUsable(row))
                {
                    continue;
                }

                totals.TryGetValue(row.Site, out var running);
                totals[row.Site] = running + double.Parse(row.Value, CultureInfo.InvariantCulture);
            }

            return totals.ToDictionary(pair => pair.Key, pair => pair.Value / seen[pair.Key]);
        }

        public static void WriteDashboard(Dictionary<string, double> averages, string path)
        {
            var lines = new List<string> { "site,average" };
            lines.AddRange(averages.Keys.OrderBy(site => site)
                .Select(site => site + "," + Math.Round(averages[site], 3)));
            File.WriteAllLines(path, lines);
        }
    }
}
