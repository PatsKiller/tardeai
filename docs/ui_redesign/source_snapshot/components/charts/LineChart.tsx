import { Line } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip } from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip)

interface LineChartProps {
  labels: string[]
  data: number[]
  color?: string
  fill?: boolean
  height?: number
}

export default function LineChart({ labels, data, color = '#4a90f4', fill = true, height = 100 }: LineChartProps) {
  return (
    <Line
      height={height}
      data={{
        labels,
        datasets: [{
          data,
          borderColor: color,
          backgroundColor: fill ? color + '18' : 'transparent',
          fill,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 4,
          borderWidth: 1.5,
        }],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, backgroundColor: '#1b2230', titleColor: '#eaeff6', bodyColor: '#b8c1d0', borderColor: '#2c3a52', borderWidth: 1 } },
        scales: {
          x: { display: false },
          y: { display: false },
        },
      }}
    />
  )
}
