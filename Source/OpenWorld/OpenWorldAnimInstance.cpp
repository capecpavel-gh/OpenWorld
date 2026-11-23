// Copyright Epic Games, Inc. All Rights Reserved.

#include "OpenWorldAnimInstance.h"
#include "Animation/AnimNodeBase.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationPoseData.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PawnMovementComponent.h"

namespace
{
	void SampleSequence(FPoseContext& Context, const UAnimSequence* Sequence, float Time)
	{
		FAnimationPoseData PoseData(Context);
		Sequence->GetAnimationPose(PoseData, FAnimExtractContext(static_cast<double>(Time), false));
	}
}

void FOpenWorldAnimInstanceProxy::PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds)
{
	Super::PreUpdate(InAnimInstance, DeltaSeconds);

	if (const UOpenWorldAnimInstance* Instance = Cast<UOpenWorldAnimInstance>(InAnimInstance))
	{
		Sequence = Instance->OverlaySequence;
		PreviousSequence = Instance->PreviousOverlaySequence;
		Time = Instance->OverlayTime;
		PreviousTime = Instance->PreviousOverlayTime;
		CrossfadeAlpha = Instance->CrossfadeAlpha;
		Weight = Instance->OverlayWeight;
		LowerBodyWeight = Instance->LowerBodyWeight;
		UpperBodyRootBone = Instance->UpperBodyRootBone;
	}
}

bool FOpenWorldAnimInstanceProxy::Evaluate_WithRoot(FPoseContext& Output, FAnimNode_Base* InRootNode)
{
	// The Anim Blueprint graph first (locomotion, jumping...)
	EvaluateAnimationNode_WithRoot(Output, InRootNode);

	// Only the main graph gets the overlay, not linked layers
	if (InRootNode == GetRootNode())
	{
		ApplyOverlay(Output);
	}

	return true;
}

void FOpenWorldAnimInstanceProxy::ApplyOverlay(FPoseContext& Output)
{
	if (Sequence == nullptr || Weight <= KINDA_SMALL_NUMBER)
	{
		return;
	}

	FPoseContext Overlay(Output);
	SampleSequence(Overlay, Sequence, Time);

	const bool bCrossfading = PreviousSequence != nullptr && CrossfadeAlpha < 1.f;
	FPoseContext Previous(Output);
	if (bCrossfading)
	{
		SampleSequence(Previous, PreviousSequence, PreviousTime);
	}

	UpdateBoneMask(Output.Pose.GetBoneContainer());

	for (const FCompactPoseBoneIndex BoneIndex : Output.Pose.ForEachBoneIndex())
	{
		const float BoneWeight = Weight * (UpperBodyMask[BoneIndex.GetInt()] ? 1.f : LowerBodyWeight);
		if (BoneWeight <= KINDA_SMALL_NUMBER)
		{
			continue;
		}

		FTransform Target = Overlay.Pose[BoneIndex];
		if (bCrossfading)
		{
			Target = Previous.Pose[BoneIndex];
			Target.BlendWith(Overlay.Pose[BoneIndex], CrossfadeAlpha);
		}

		FTransform& Bone = Output.Pose[BoneIndex];
		Bone.BlendWith(Target, BoneWeight);
		Bone.NormalizeRotation();
	}
}

void FOpenWorldAnimInstanceProxy::UpdateBoneMask(const FBoneContainer& Bones)
{
	const int32 NumBones = Bones.GetCompactPoseNumBones();
	if (UpperBodyMask.Num() == NumBones && MaskSerialNumber == Bones.GetSerialNumber() && MaskRootBone == UpperBodyRootBone)
	{
		return;
	}

	const FReferenceSkeleton& RefSkeleton = Bones.GetReferenceSkeleton();
	const int32 UpperBodyRoot = RefSkeleton.FindBoneIndex(UpperBodyRootBone);

	UpperBodyMask.SetNumZeroed(NumBones);
	for (int32 Index = 0; Index < NumBones; ++Index)
	{
		bool bUpperBody = false;
		int32 MeshBone = Bones.MakeMeshPoseIndex(FCompactPoseBoneIndex(Index)).GetInt();
		while (MeshBone != INDEX_NONE)
		{
			if (MeshBone == UpperBodyRoot)
			{
				bUpperBody = true;
				break;
			}
			MeshBone = RefSkeleton.GetParentIndex(MeshBone);
		}
		UpperBodyMask[Index] = bUpperBody ? 1 : 0;
	}

	MaskSerialNumber = Bones.GetSerialNumber();
	MaskRootBone = UpperBodyRootBone;
}

FAnimInstanceProxy* UOpenWorldAnimInstance::CreateAnimInstanceProxy()
{
	return new FOpenWorldAnimInstanceProxy(this);
}

void UOpenWorldAnimInstance::PlayOverlay(UAnimSequence* Sequence, float BlendInTime, float BlendOutTime)
{
	if (Sequence == nullptr)
	{
		return;
	}

	if (OverlaySequence != nullptr && OverlayWeight > 0.f)
	{
		// Cross-fade from the pose the current overlay is in right now
		PreviousOverlaySequence = OverlaySequence;
		PreviousOverlayTime = OverlayTime;
		CrossfadeAlpha = 0.f;
	}
	else
	{
		PreviousOverlaySequence = nullptr;
		CrossfadeAlpha = 1.f;
	}

	OverlaySequence = Sequence;
	OverlayTime = 0.f;
	OverlayStartWeight = OverlayWeight;
	OverlayBlendIn = FMath::Max(BlendInTime, 0.f);
	OverlayBlendOut = FMath::Max(BlendOutTime, 0.f);
}

void UOpenWorldAnimInstance::StopOverlay(float BlendOutTime)
{
	if (OverlaySequence != nullptr)
	{
		// Jump to the start of a blend-out of the requested length
		OverlayBlendOut = FMath::Max(BlendOutTime, KINDA_SMALL_NUMBER);
		OverlayTime = FMath::Max(OverlayTime, OverlaySequence->GetPlayLength() - OverlayBlendOut);
	}
}

void UOpenWorldAnimInstance::NativeUpdateAnimation(float DeltaSeconds)
{
	Super::NativeUpdateAnimation(DeltaSeconds);

	// Legs follow the overlay only while standing on the ground
	bool bStanding = true;
	if (const APawn* Pawn = TryGetPawnOwner())
	{
		const UPawnMovementComponent* Movement = Pawn->GetMovementComponent();
		bStanding = Pawn->GetVelocity().Size2D() <= FullBodyMaxSpeed && !(Movement && Movement->IsFalling());
	}
	LowerBodyWeight = FMath::FInterpTo(LowerBodyWeight, bStanding ? 1.f : 0.f, DeltaSeconds, LowerBodyBlendSpeed);

	if (OverlaySequence == nullptr)
	{
		OverlayWeight = 0.f;
		return;
	}

	OverlayTime += DeltaSeconds;

	const float Length = OverlaySequence->GetPlayLength();
	if (OverlayTime >= Length)
	{
		OverlaySequence = nullptr;
		PreviousOverlaySequence = nullptr;
		OverlayWeight = 0.f;
		CrossfadeAlpha = 1.f;
		return;
	}

	const float In = OverlayBlendIn > 0.f ? FMath::Clamp(OverlayTime / OverlayBlendIn, 0.f, 1.f) : 1.f;
	const float Out = OverlayBlendOut > 0.f ? FMath::Clamp((Length - OverlayTime) / OverlayBlendOut, 0.f, 1.f) : 1.f;
	OverlayWeight = FMath::Min(FMath::Lerp(OverlayStartWeight, 1.f, FMath::SmoothStep(0.f, 1.f, In)), FMath::SmoothStep(0.f, 1.f, Out));

	if (PreviousOverlaySequence != nullptr)
	{
		CrossfadeAlpha = OverlayBlendIn > 0.f ? FMath::Clamp(OverlayTime / OverlayBlendIn, 0.f, 1.f) : 1.f;
		if (CrossfadeAlpha >= 1.f)
		{
			PreviousOverlaySequence = nullptr;
		}
	}
}
