"use client";

import { useParams } from "next/navigation";
import { DeviceDetail } from "@/components/organisms/device-detail/DeviceDetail";

export default function DeviceDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <DeviceDetail deviceId={id} />;
}
