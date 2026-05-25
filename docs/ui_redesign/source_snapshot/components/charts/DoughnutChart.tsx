import { Doughnut } from 'react-chartjs-2'
import { Chart as ChartJS, ArcElement, Tooltip } from 'chart.js'

ChartJS.register(ArcElement, Tooltip)

const COLORS = ['#4a90f4', '#0ecb81', '#f6465d', '#f0b90b', '#a78bfa', '#38bdf8', '#fb923c', '#6ee7b7', '#f472b6', '#94a3b8']

interface DoughnutChartProps {
  labels: string[]
  data: number[]
  height?: number
  colors?: string[]
}

export default function DoughnutChart({ labels, data, height = 160, colors }: DoughnutChartProps) {
  return (
    <Doughnut
      height={height}
      data={{
        labels,
        datasets: [{
          data,
          backgroundColor: colors || COLORS.slice(0, data.length),
          borderColor: '#131820',
          borderWidth: 2,
        }],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        cutout: '65%',
        plugins: {
          legend: { display: false },
          tooltip: { backgroundColor: '#1b2230', titleColor: '#eaeff6', bodyColor: '#b8c1d0', borderColor: '#2c3a52', borderWidth: 1 },
        },
      }}
    />
  )
}
