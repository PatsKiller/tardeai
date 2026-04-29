import { Bar } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip } from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

interface BarChartJSProps {
  labels: string[]
  data: number[]
  colors?: string[]
  height?: number
}

export default function BarChartJS({ labels, data, colors, height = 100 }: BarChartJSProps) {
  const defaultColors = data.map(v => v >= 0 ? '#0ecb81' : '#f6465d')
  return (
    <div style={{ position: 'relative', height }}>
    <Bar
      data={{
        labels,
        datasets: [{
          data,
          backgroundColor: colors || defaultColors,
          borderRadius: 2,
          maxBarThickness: 28,
        }],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { backgroundColor: '#1b2230', titleColor: '#eaeff6', bodyColor: '#b8c1d0', borderColor: '#2c3a52', borderWidth: 1 } },
        scales: {
          x: { ticks: { color: '#4e5a6e', font: { size: 9 } }, grid: { display: false }, border: { display: false } },
          y: { display: false, beginAtZero: true },
        },
      }}
    />
    </div>
  )
}
