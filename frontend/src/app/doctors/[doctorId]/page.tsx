"use client";

import { use } from "react";
import { BookingStepper } from "@/components/BookingStepper";

export default function DoctorProfilePage({
  params,
}: {
  params: Promise<{ doctorId: string }>;
}) {
  const { doctorId } = use(params);
  return <BookingStepper doctorId={doctorId} />;
}
